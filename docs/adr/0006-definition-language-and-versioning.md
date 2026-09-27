# 0006: Definition language and versioning

- Status: accepted
- Date: 2026-09-27
- Deciders: maintainers

## Context

The brief makes YAML definitions the source of truth for frameworks, metrics, controls and dashboards, with structured filters and no expression language. Every measurement has to point back to the exact definition that produced it, and a changed definition must never rewrite history. The data model also lists collector instances (plugin, config, secret references, schedule), and those need a home.

## Decision

Format and parsing:

- One YAML file per definition, or a list of definitions in one file, under `content/{frameworks,metrics,controls,dashboards,collectors}/`.
- PyYAML parses with a `SafeLoader` subclass that also rejects duplicate keys. No tags, no Python objects. Files over 1 MB are refused.
- Pydantic v2 models in `dsec_metrics.core.definitions` validate every file. All models forbid unknown fields and are frozen.
- `dsec-metrics validate` reports every schema problem and every broken cross-reference (framework requirements, control and dashboard metric ids, collector instances, and queries the plugin offers) and exits non-zero if there are any.

Language:

- Filters are `{field, op, value}` with a fixed operator set: `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `not_in`, `exists`, `missing`. A missing field compares as null. Ordering operators need both sides numeric, or both strings. Booleans never equal numbers.
- Evaluation kinds are a discriminated union on `kind`: `count`, `sum`, `ratio`, `percentage`, `median`, `percentile` (nearest rank), `age_over`, `sla_breach`, `latest_value`. `group_by` accepts only the four measurement dimensions.
- Threshold bands use inclusive `min` and `max` and exclusive `above` and `below`. Bands are tried in the order green, amber, red. A value that matches none is red. The override with the most matching dimensions wins and replaces only the bands it names.
- Collector instances are definitions too, under `content/collectors/`. Their `config` may hold secret references (`env://`, `file://`, later `vault://`), never secret values.
- Framework packs hold IDs and our own short titles. `text` is accepted only when the pack sets `public_domain: true`, which only NIST CSF 2.0 does.

Versioning:

- A definition's hash is SHA-256 over canonical JSON of the validated model: sorted keys, no insignificant whitespace, UTF-8, no NaN or infinity.
- Syncing content stores each new hash as a new row in `definitions` with the next version number and marks it current. Old rows stay.
- Measurements store the definition id, hash and version, and are insert-only, unique on metric, definition hash, `as_of` and dimension slice. Recomputing after a change adds rows under the new version.

## Consequences

- Reviewers see definition changes as YAML diffs, and every number can be traced to a version and a hash.
- Anything the language cannot express needs a new evaluation kind in code, reviewed like any other change. This is deliberate.
- Two formatting-only edits of a file give the same hash, because the hash is taken after validation.
- PyYAML is not named in the brief. It is the most widely reviewed YAML parser for Python and is used only through the safe loader; it was flagged for approval in the M1 plan.
- Framework packs cover the requirements the default controls use, not whole standards, so teams will extend them.
