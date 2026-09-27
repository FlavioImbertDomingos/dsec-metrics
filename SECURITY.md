# Security policy

dsec-metrics is built to run inside regulated networks, so we take reports seriously and handle them privately.

## Supported versions

The project is pre-release. Until 1.0, only the latest commit on `main` and the most recent tagged release receive security fixes.

| Version | Supported |
| --- | --- |
| `main` | yes |
| latest `0.x` release | yes |
| older releases | no |

## Reporting a vulnerability

Do not open a public issue, pull request or discussion for a security problem.

Report it through GitHub private vulnerability reporting: open the repository's **Security** tab and choose **Report a vulnerability**. The report is visible only to the maintainers.

Please include:

- the affected version or commit
- the component (API, worker, web, CLI, container image, CI workflow, Compose files)
- steps to reproduce, or a proof of concept
- the impact you expect, and any mitigations you know of

Use synthetic data in your report. Never send real cardholder data, credentials or customer information.

## What to expect

- Acknowledgement within 3 business days.
- An initial assessment, including a severity rating, within 10 business days.
- A fix or a documented mitigation for high and critical issues within 30 days of confirmation, and for other issues in the next planned release.
- Credit in the release notes and the published advisory, unless you ask to stay anonymous.

We publish fixed issues as GitHub Security Advisories and request a CVE where one is warranted.

## Safe harbor

We will not pursue or support legal action against anyone who, in good faith, researches and reports a vulnerability under this policy: testing only against your own installation, avoiding privacy violations and service disruption, and giving us reasonable time to fix the issue before disclosure.

## Scope

In scope: the code in this repository, the container images published from it, and its release and CI workflows.

Out of scope: vulnerabilities in third-party dependencies that are already public (report those upstream; we track them through Dependabot, pip-audit, osv-scanner and trivy), and findings that need a compromised host, identity provider or database administrator account to exploit.

## How the project handles security

- Threat model: [docs/security/threat-model.md](docs/security/threat-model.md)
- CI security gates and the suppression process: [docs/adr/0005-security-gate-policy.md](docs/adr/0005-security-gate-policy.md)
- Release images are signed with cosign keyless signing and ship with a CycloneDX SBOM and SLSA provenance.
