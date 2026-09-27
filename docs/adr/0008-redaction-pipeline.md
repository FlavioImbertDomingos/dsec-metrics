# 0008: Redaction pipeline

- Status: accepted
- Date: 2026-09-27
- Deciders: maintainers

## Context

The brief requires that no full card number or sensitive authentication data is ever stored, and that collector output goes through a redaction pipeline that drops sensitive fields, masks card-number-like values to first six and last four, and records what it changed. Collectors are plugins, so the pipeline cannot rely on each plugin getting this right.

## Decision

- Redaction is a pure function in `dsec_metrics.core.redaction`, applied by the pipeline to every record batch before it is hashed or stored. Plugins cannot skip it.
- Dropped fields: the collector's `sensitive_fields`, the instance's `sensitive_fields` from its config, and a global list (`cvv`, `cvv2`, `cvc`, `cvc2`, `cid`, `pin`, `pin_block`, `track1`, `track2`, `track_data`, `magstripe`, `password`, `secret`, `private_key`). Names are compared after lowercasing and removing non-alphanumerics, so `Track-2`, `track_2` and `TRACK2` all match.
- Masking: any run of 13 to 19 digits, optionally separated by single spaces or dashes, that passes the Luhn check is replaced by its first six digits, asterisks, and its last four. This applies inside longer strings, to integer values, and to keys and values at any depth in nested objects and lists.
- Each batch stores a summary: the number of values masked and a count of dropped fields by name. Values are never recorded in the summary.
- The batch hash is computed over the redacted records, so evidence verification never needs the original data.
- A test pushes Luhn-valid numbers in several shapes through each collector path (the `file` collector's CSV and JSON, and the `sample` collector), then reads every row of every application table and fails if any number appears unmasked, even with separators removed.

## Consequences

- A Luhn-valid number that is not a card number (some order or account numbers) is also masked. We accept the false positives; the brief asks for this rule.
- Card numbers written with other separators, or split across fields, are not caught. Collector authors must list fields that can hold them in `sensitive_fields`, and the plugin guide says so.
- Masked values keep the issuer prefix and last four, which is what PCI DSS allows to be displayed and is enough for an analyst to follow up.
- Redaction happens in the worker process, so raw collector output exists in memory there. It is never logged or written anywhere before redaction.
