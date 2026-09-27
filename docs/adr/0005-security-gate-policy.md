# 0005: Security gate policy and suppressions

- Status: accepted
- Date: 2026-09-26
- Deciders: maintainers

## Context

The brief requires CI to fail on high or critical findings from a fixed set of tools, and forbids disabling or weakening a gate to get a build through. Scanners sometimes report findings with no fix available, or findings that do not apply. We need a way to handle those without weakening the gates.

## Decision

Gates and thresholds (all run by `make ci` and by `.github/workflows/ci.yml`):

| Gate | Tool | Fails on |
| --- | --- | --- |
| Python lint and types | ruff (security rules included), mypy `--strict` | any finding |
| Web lint and types | ESLint `--max-warnings 0`, `tsc --strict`, Prettier | any finding |
| Tests | pytest and Vitest | any failure; coverage below 80 percent overall or 90 percent for `core` |
| SAST | bandit | medium severity and medium confidence or above (stricter than the brief) |
| SAST | semgrep (`p/owasp-top-ten`, `p/python`, `p/typescript`, `p/react`, `p/dockerfile`, `p/secrets`), metrics off | ERROR severity |
| Dependencies | pip-audit on every locked Python package | any known vulnerability |
| Dependencies | osv-scanner on `uv.lock` and `pnpm-lock.yaml` | any known vulnerability |
| Secrets | gitleaks over full history | any finding |
| Workflows | zizmor, SHA pinning enforced | medium or above |
| Images | trivy image scan of both images, trivy config scan of the Dockerfiles | high or critical, including unfixed |
| Accessibility | axe-core in Playwright, WCAG 2.2 AA tags | any violation |
| Commits | DCO sign-off | any commit without `Signed-off-by` |

Supply-chain rules: every GitHub Action is pinned to a commit SHA; every container image to a digest; Python and web dependencies are hash-locked; uv and pnpm ignore releases younger than seven days; pnpm runs no install scripts.

Suppressions:

- Allowed only in tracked files: `.trivyignore.yaml` (with `statement` and `expired_at`), `osv-scanner.toml` (with `reason` and `ignoreUntil`), `# nosec BXXX: reason`, `# nosemgrep: rule-id` with a reason, and `.gitleaks.toml` allowlist entries with a description.
- Each needs maintainer approval in review.
- Expired entries stop applying, so the finding fails the build again.
- `make suppressions` lists them all, and CI prints the list in the job summary.

## Consequences

- Base-image CVEs without a fix will sometimes block builds. The answer is an approved, dated suppression, not `--ignore-unfixed`.
- Semgrep registry rules are downloaded at scan time and carry their own license. An air-gapped fork of the pipeline would need them vendored.
- Keyless cosign writes to the public Sigstore transparency log, which records the repository and workflow identity. Air-gapped verification needs the signature bundle shipped with the image; M5 documents this.
