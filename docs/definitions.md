# Definition language

Frameworks, metrics, controls, dashboards and collector instances are YAML files under `content/`. They are the source of truth: the database keeps a versioned copy of each, and every measurement points to the version that produced it. [ADR-0006](adr/0006-definition-language-and-versioning.md) explains the design.

```
content/
  frameworks/   framework packs
  metrics/      KPI, KRI and KCI definitions
  controls/     internal controls
  dashboards/   dashboard layouts
  collectors/   configured collector instances
```

A file holds one definition, or a YAML list of definitions of the same kind. Files are parsed with a safe loader that rejects duplicate keys and anything other than plain data. Unknown fields are errors.

Check your changes with:

```sh
dsec-metrics validate
```

It prints every schema problem and every broken reference with the file it came from, and exits non-zero if there are any.

## Metrics

```yaml
id: KRI-03                  # letters, a dash, 2 to 4 digits
name: Exceptions open more than 180 days
type: kri                   # kpi, kri or kci
question: Are exceptions staying temporary?
owner: data-security-exceptions-lead
audience: [risk_committee, management]   # team_operations, management, risk_committee
source:
  collector: sample         # a collector instance id from content/collectors
  query: open_exceptions    # a query that instance offers
  params: {}                # optional scalar parameters passed to the collector
evaluation:
  kind: age_over
  date_field: approved_at
  days: 180
  filters:
    - {field: status, op: eq, value: approved}
  group_by: [business_unit]
frequency: monthly          # daily, weekly, monthly, quarterly
thresholds:
  green: {max: 5}
  amber: {max: 15}
  red: {above: 15}
  overrides:
    - {dimension: {business_unit: cards}, red: {above: 8}}
action_when_red: Escalate owners to the business unit CIO.
frameworks: ["nist-csf-2.0:GV.RM", "pci-dss-4.0.1:12.3.1"]
baseline: {value: 22, method: manual count from register, date: 2026-10-31}
target: 5                   # optional
unit: count                 # count, percent, days, ratio or value
higher_is_better: false
approved_by: [data-security-manager, technology-risk, internal-audit]
review_by: 2027-04-30
```

### Filters

A filter is `{field, op, value}`. Every filter in a list must pass.

| `op` | Passes when |
| --- | --- |
| `eq`, `ne` | the field equals, or does not equal, `value` |
| `gt`, `gte`, `lt`, `lte` | both sides are numbers, or both are strings, and the comparison holds |
| `in`, `not_in` | the field is, or is not, one of the values in the `value` list |
| `exists`, `missing` | the field is present and not null, or absent or null |

A missing field compares as null. `true` never equals `1`. There are no expressions, functions or templates, and nothing in a definition is ever executed.

### Evaluation kinds

All kinds accept `filters` and `group_by`. `group_by` takes any of `business_unit`, `application`, `environment` and `region`; records without the dimension are grouped as `unassigned`.

| `kind` | Extra fields | Value |
| --- | --- | --- |
| `count` | | records that pass the filters |
| `sum` | `field` | sum of a numeric field |
| `ratio` | `numerator`, `denominator` (filter lists), optional `numerator_field`, `denominator_field`, `scale` | numerator divided by denominator, times `scale`; each side counts records, or sums its field when one is given |
| `percentage` | as `ratio`, without `scale` | the same ratio in percent |
| `median` | `field` | median of a numeric field |
| `percentile` | `field`, `percentile` (0 to 100) | nearest-rank percentile |
| `age_over` | `date_field`, `days` | records whose date is more than `days` before `as_of` |
| `sla_breach` | `opened_field`, optional `closed_field`, `sla_days`, `as_percentage` | records open longer than `sla_days`, measured to their close date or to `as_of`; with `as_percentage` the share of records in breach |
| `latest_value` | `field`, `order_by` | `field` of the record with the greatest `order_by` value |

An empty denominator, or no numeric values for `median`, `percentile` or `latest_value`, gives no value and the status `unknown`.

### Thresholds

Each band is a set of bounds: `min` and `max` are inclusive, `above` and `below` are exclusive. Bands are tried in the order green, amber, red, and the first match wins. A value that matches no band is red. `amber` and `red` are optional.

Overrides apply to dimension slices. An override matches when every dimension it names has the given value, the override naming the most dimensions wins, and it replaces only the bands it lists.

A metric is `unknown` when there is no data, or when the last successful collection is older than twice its frequency. `unknown` is never shown as green.

### What a measurement records

For the overall value and each slice: the value, status, definition hash and version, the SHA-256 of every input batch, the change from the previous period, and a `calculation` record with the filtered record counts and intermediate numbers. The overall value also carries the change from baseline and the distance to target.

## Controls

```yaml
id: DS-KM-04                # 2-4 letters, 2-4 letters, 2-3 digits
name: Cryptographic keys are rotated at the end of their cryptoperiod
owner: crypto-services-lead
description: Optional free text.
requirements: ["pci-dss-4.0.1:3.7.4", "nist-csf-2.0:PR.DS-01"]
metrics: [KRI-04]
evidence:
  - {collector: sample, query: crypto_keys, retain_days: 400}
```

## Framework packs

```yaml
id: pci-dss-4.0.1
name: PCI DSS
version: 4.0.1
source_url: https://www.pcisecuritystandards.org/
requirements:
  - {ref: "3.7.4", short_title: Key changes at end of cryptoperiod}
```

Short titles are written by us. Do not copy requirement text from PCI DSS, ISO/IEC 27001 or the AICPA Trust Services Criteria: those documents are copyrighted. A pack may include `text` only when it sets `public_domain: true`, as the NIST CSF 2.0 pack does.

References elsewhere use `pack-id:ref`. A reference to a category, such as `nist-csf-2.0:GV.RM`, is valid when the pack has requirements under it.

## Dashboards

```yaml
id: risk-committee
title: Risk committee
audience: risk_committee
refresh: monthly
layout:
  - {widget: rag_list, metrics: [KRI-01, KRI-03, KRI-04, KRI-05], width: 12}
  - {widget: trend, metric: KRI-03, periods: 12, width: 6}
  - {widget: heatmap, rows: business_unit, columns: metric, value: status, width: 6}
```

Widget types: `stat`, `trend`, `bar`, `table`, `rag_list`, `heatmap`, `exceptions_aging`, `findings_burndown`. `width` is in twelfths of the page.

## Collector instances

```yaml
id: exports
plugin: file
description: Monthly exports from the GRC tool.
config:
  base_dir: /data/exports
  files: {open_exceptions: exceptions.csv}
  sensitive_fields: [requester_email]
schedule: "5 2 * * *"       # five-field cron in UTC, or omit for manual runs
```

`config` is validated by the plugin's own model. Secrets are references such as `env://GRC_TOKEN` or `file:///run/secrets/grc-token`, never values. Schedules accept numbers, `*`, ranges, steps and lists; names such as `MON` are not supported.

## Registers

The exceptions and findings registers come from collector data. A register names the source; the GRC tool stays the system of record.

```yaml
id: exceptions              # exceptions or findings
source: {collector: grc, query: open_exceptions}
```

Records in an exceptions register are read with these fields: `exception_id` and `status` (required), `control_id`, `reason`, `compensating_controls`, `risk_rating`, `owner`, `root_cause`, `approved_at`, `expires_at` (dates as `YYYY-MM-DD`), and the four dimensions. Findings use `finding_id`, `severity` and `status` (required), `source`, `control_id`, `owner`, `opened`, `due_date`, `repeat`, and the dimensions. Records without the required fields are skipped and counted. Ages are counted to the batch's `as_of` date, so the register reads the same whenever it is opened.

## Versioning

On each sync, a definition's SHA-256 is computed over canonical JSON of the validated model. A new hash becomes a new version; the old version stays, and so do the measurements made with it. Reformatting a file without changing its meaning does not create a version.
