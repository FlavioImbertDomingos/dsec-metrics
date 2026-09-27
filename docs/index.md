# dsec-metrics

![Placeholder home page](assets/screenshot.png)

dsec-metrics is a self-hosted compliance metrics and audit evidence platform for data security teams at regulated companies. Metric and control definitions live as YAML in version control. The platform measures them against data from read-only collectors, shows one dashboard per audience, and builds evidence packages an auditor can verify independently: every number links back to its definition version, query and hashed source data, and every package carries a signed SHA-256 manifest.

It runs inside your network, behind your identity provider, with no telemetry.

## Status

The project is pre-alpha. Milestone M0 is in place: the Compose stack, development sign-in, container images and CI with every security gate. Definitions and the evaluator arrive in M1, dashboards in M2 and audit reports in M3.

## Where to go next

- [Getting started](getting-started.md) runs the stack on your machine.
- [Architecture](architecture.md) covers the modules and how they talk to each other.
- [Deploying with Docker Compose](deployment/compose.md) covers settings, secrets and TLS.
- [Security overview](security/index.md) and the [threat model](security/threat-model.md) are written for a security reviewer.
- [Decisions](adr/index.md) lists every architecture decision record.
