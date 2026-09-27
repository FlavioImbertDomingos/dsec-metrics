# Changelog

All notable changes to this project are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Security

- APScheduler is not used, because its JSON and CBOR serializers instantiate classes named in stored data (CVE-2026-31072, no fixed release). The worker uses its own scheduler that stores only a job name and string arguments (ADR-0007).

### Added

- M1 definitions and evaluator: Pydantic schemas for frameworks, metrics, controls, dashboards and collector instances; `dsec-metrics validate`, `collect`, `evaluate`, `demo` and `status`; the evaluator with all nine v1 evaluation kinds, threshold bands and per-dimension overrides; the redaction pipeline; the plugin SDK with `file` and `sample` collectors and `env` and `file` secret providers; versioned definitions and insert-only measurements (migration 0002); a Postgres-backed scheduler in the worker; default content (four framework packs, 16 metrics, 40 controls, three dashboards); ADR-0006 to ADR-0008; docs for the definition language and the plugin SDK.
- M0 foundations: repository skeleton, community files, CI with every security gate, container images, Docker Compose stack with development sign-in, ADR-0001 to ADR-0005 and a first threat model draft.
