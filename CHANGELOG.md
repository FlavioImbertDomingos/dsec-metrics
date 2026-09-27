# Changelog

All notable changes to this project are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Security

- APScheduler is not used, because its JSON and CBOR serializers instantiate classes named in stored data (CVE-2026-31072, no fixed release). The worker uses its own scheduler that stores only a job name and string arguments (ADR-0007).

### Added

- M4 real collectors: `rest`, `aws`, `vault`, `jira`, `servicenow` and `github` collectors; an HTTP layer in the plugin SDK with timeouts, retries, backoff, pagination helpers, size limits and read-only requests; an outbound policy with an operator host allowlist and SSRF protection on every request (`DSEC_COLLECTOR_ALLOWED_HOSTS`, `DSEC_COLLECTOR_ALLOW_HTTP_HOSTS`); AWS Signature Version 4 without the AWS SDK; `dsec-metrics plugin new collector`, `plugin list` and `test-connection`; `FixtureTransport` and `fixture_policy` for contract tests; a `collectors` network in Compose for the worker only; permission docs for every collector and a plugin author guide; ADR-0013 and ADR-0014.
- Report renderers are registered in the `dsec_metrics.renderers` entry point group and loaded through it.
- M3 audit reports: the six report types; signed evidence packages (ZIP with report, workbook, JSON, evidence batches, definitions, CSV tables, manifest and Ed25519 signature); `dsec-metrics verify` and `reproduce`; `keys generate` and `report build`; roles (`admin`, `metric_owner`, `reviewer`, `viewer`, `auditor`, `service`) with auditor grants and time-limited, personal download links; a hash-chained, append-only audit log with `audit verify` (migration 0004); Reports, Audit room and Audit log screens; ADR-0010 to ADR-0012; docs for reports and the audit log.
- M2 dashboards: read API for metrics, measurements, batches, controls, exceptions, findings and dashboards; rate and request size limits on every route (migration 0003); register definitions for exceptions and findings; the overview, three audience dashboards, metric detail, measurement and batch drill-down, controls, exceptions and findings screens with light and dark mode, filters in the URL, table views for every chart and a print layout; Playwright and axe coverage for every screen; ADR-0009; docs for dashboards and the API.
- M1 definitions and evaluator: Pydantic schemas for frameworks, metrics, controls, dashboards and collector instances; `dsec-metrics validate`, `collect`, `evaluate`, `demo` and `status`; the evaluator with all nine v1 evaluation kinds, threshold bands and per-dimension overrides; the redaction pipeline; the plugin SDK with `file` and `sample` collectors and `env` and `file` secret providers; versioned definitions and insert-only measurements (migration 0002); a Postgres-backed scheduler in the worker; default content (four framework packs, 16 metrics, 40 controls, three dashboards); ADR-0006 to ADR-0008; docs for the definition language and the plugin SDK.
- M0 foundations: repository skeleton, community files, CI with every security gate, container images, Docker Compose stack with development sign-in, ADR-0001 to ADR-0005 and a first threat model draft.
