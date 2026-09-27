# Reports and evidence packages

A report is a signed ZIP that an auditor can check without access to dsec-metrics. [ADR-0011](adr/0011-evidence-packages.md) explains the design.

## Report types

| Type | Scope | What it holds |
| --- | --- | --- |
| `control` | one control | Requirements, metrics with their newest value in the period, the evidence collected for the control, its exceptions and findings |
| `framework` | one framework pack, optionally some requirements (`3`, `8.4`) | Every control mapped to those requirements, each as in the control package |
| `reproducibility` | one metric, optionally one measurement | The definition version, the input batches and the calculation record, so the number can be recomputed |
| `risk_committee` | none | Key risk indicators for the committee with status, owner and the action for anything red |
| `management` | none | Program indicators with every value in the period, baseline and target |
| `exceptions` | none | The exceptions register with age, root cause and expiry |

Every type takes a period (start and end date, at most two years) and an optional "Prepared for" line. Reports use stored data only: the newest measurement of each metric in the period, and the newest successful collection in the period for each evidence source and register.

## Building one

In the UI, open Reports, pick the type, scope and period, and select Build and sign. From the command line:

```sh
docker compose exec api dsec-metrics report build framework \
  --framework pci-dss-4.0.1 --requirement 3 --requirement 8 \
  --period-start 2026-07-01 --period-end 2026-09-30 \
  --prepared-for "Example QSA" --output /tmp/pci-q3.zip
```

Building a report needs the `admin`, `metric_owner` or `reviewer` role. Every package is stored, and generating one is written to the audit log.

## What is in the package

```
report.pdf or report.html    cover, contents, scope and method, summary by status, one
                             section per control, chain of custody, appendix of definitions
report.xlsx                  one sheet per table
report.json                  the same tables as JSON
evidence/batches/<sha>.json  every source batch used, with its redacted records
evidence/definitions/        the metric definition versions used
evidence/tables/*.csv        every table as CSV
manifest.json                every file with SHA-256, size, source and record
manifest.sig                 Ed25519 signature over manifest.json
```

The default container image produces `report.html` instead of `report.pdf` until PDF rendering is enabled in the image; see [ADR-0010](adr/0010-pdf-rendering.md). The HTML is the same document and prints to PDF from any browser. Spreadsheet cells and CSV values that start with `=`, `+`, `-` or `@` are stored as text, so a record cannot run a formula.

## Verifying a package

Give the auditor the package and, separately, the public key or its fingerprint (Reports shows both; `GET /api/reports/public-key` returns them). Then:

```sh
dsec-metrics verify package.zip --fingerprint <fingerprint>
# or
dsec-metrics verify package.zip --public-key signing.pub
```

It checks the signature, that every listed file is present with the listed size and hash, and that nothing else is in the archive. It prints every problem and exits with 1 if there is one. It needs no database and no network connection.

The format is simple enough to check with other tools: `manifest.sig` is a base64 Ed25519 signature over the exact bytes of `manifest.json`, and each file's SHA-256 is in the manifest.

For a reproducibility package, `dsec-metrics reproduce package.zip` also recomputes the number from the definition and batches in the package and compares it with the reported value.

## The signing key

The key is an Ed25519 private key in PKCS#8 PEM, passed as a Docker secret and named by `DSEC_REPORT_SIGNING_KEY_FILE`.

- Development: `make dev-secrets` creates `deploy/compose/secrets/report_signing_key`. If your OpenSSL cannot make Ed25519 keys (the LibreSSL that ships with macOS cannot), it leaves an empty placeholder; run `make signing-key` after the stack is up.
- Production: create the key once with `dsec-metrics keys generate --private-key signing.pem --public-key signing.pub`, keep a backup, and publish the fingerprint to your auditors. Without a key, report generation returns 503.

## Auditor access

See [Audit log and auditors](audit.md).
