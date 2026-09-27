# 0011: Evidence packages, signing and verification

- Status: accepted
- Date: 2026-09-27
- Deciders: maintainers

## Context

The brief requires report packages that an auditor can verify independently: a ZIP with the report, the evidence, a manifest of SHA-256 hashes and an Ed25519 signature over the manifest, and a `verify` command that fails on any change.

## Decision

Package layout:

```
report.pdf | report.html     the report (ADR-0010)
report.xlsx                  every table, one sheet each
report.json                  the same data for other tools
evidence/batches/<sha>.json  every source batch used, redacted records included
evidence/definitions/*.json  the metric definition versions used
evidence/tables/*.csv        every table as CSV
manifest.json                files, hashes, sizes, sources, report metadata, signer
manifest.sig                 base64 Ed25519 signature over the bytes of manifest.json
```

- Every manifest entry has the path, SHA-256, size, media type, source (collector and query, or the renderer and its version), collection time, and the record it belongs to (batch hash and run id, or metric id, definition version and measurement id).
- The manifest also embeds the raw public key and its fingerprint (SHA-256 of the 32-byte key). The fingerprint is printed on the report's cover and in the chain-of-custody section.
- ZIP entries are sorted with fixed timestamps; evidence files are canonical JSON. Rebuilding from the same stored data gives the same evidence hashes.
- Reports are built from stored data only: the newest measurement per metric in the period, and the newest successful collection in the period for each evidence source and register.
- Packages are stored whole in Postgres (`report_packages`), never modified, so a download months later is the file that was signed.
- The signing key is a PKCS#8 PEM file from a Docker secret (`DSEC_REPORT_SIGNING_KEY_FILE`). `make dev-secrets` creates one; `dsec-metrics keys generate` creates one for production. No private key is stored in the database. M5 adds key provider plugins (Vault transit, KMS).

Verification (`dsec-metrics verify`, no database and no network):

- The archive has exactly one manifest and one signature, and no duplicate entries.
- The signature is valid for the manifest bytes, with a pinned key (`--public-key` or `--fingerprint`) when given; otherwise the embedded key is used and the output says the key is unpinned.
- Every listed file exists with the listed size and SHA-256; nothing unlisted is present; no path is absolute or climbs out of the archive.
- Every problem is reported, and the exit code is 1 if there is any.

Reproduction (`dsec-metrics reproduce`): for a metric reproducibility package, verify it, check each batch file's records hash to the batch hash, rerun the evaluator on the included definition and batches, and compare the value and status with the reported ones.

The e2e suite also checks packages with Node's own crypto and a 50-line ZIP reader, so the format is verifiable without our code.

## Consequences

- An auditor needs only the package and the public key fingerprint, delivered separately (for example in the engagement letter).
- Packages can be large when evidence batches are large; the brief's retention settings (M5) will bound them.
- Anyone holding the signing key can produce packages that verify. The key file is a Docker secret readable only by the app; M5 moves it behind a key provider so it never sits on disk.
