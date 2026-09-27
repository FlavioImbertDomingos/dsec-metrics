# Contributing to dsec-metrics

Thanks for helping. This page covers the development setup, the rules every change follows, and how review works.

## Ground rules

These are not negotiable, and CI enforces most of them.

- Never commit real company data, real credentials, real hostnames or employer names, including in fixtures, screenshots and commit messages. Use synthetic data and `example.com` / `example.test` names.
- Never copy requirement text from PCI DSS, ISO/IEC 27001 or the AICPA Trust Services Criteria. Framework packs hold IDs and short titles we write ourselves. NIST CSF 2.0 text may be included.
- Never use `eval`, `exec`, `pickle` or a free-form expression language on definitions or user input.
- Collectors are read-only. No collector may write to a source system.
- No telemetry, and no outbound calls other than those an operator configures.
- Never disable or weaken a CI security gate to get a build to pass. Fix the cause, or propose a time-limited suppression as described in [ADR-0005](docs/adr/0005-security-gate-policy.md).

## Development setup

You need:

- Docker with Compose v2
- [uv](https://docs.astral.sh/uv/) 0.12 or later
- Node.js 24 (see `.nvmrc`) and pnpm (the version is pinned in `web/package.json`; `corepack enable` or `npm i -g pnpm` both work)
- `make` and `openssl`

```sh
make setup          # install Python and web dependencies
make dev-secrets    # create local passwords and a development CA (once)
docker compose up -d --wait
```

Open <https://localhost> and sign in as `dev-admin` with the password `make dev-secrets` printed. It is also in `deploy/compose/secrets/dev_admin_password`.

For day-to-day work with reload on save:

```sh
docker compose -f compose.yaml -f compose.dev.yaml up
```

## Running the checks

`make ci` runs the same jobs as GitHub Actions, in the same order, with the same tool versions. Run it before you open a pull request. Individual targets:

| Target | What it runs |
| --- | --- |
| `make lint` | ruff, mypy --strict, eslint, tsc, prettier --check |
| `make test` | pytest (with Postgres through Testcontainers) and Vitest, with coverage gates |
| `make scan` | bandit, semgrep, pip-audit, osv-scanner, gitleaks, zizmor |
| `make images` | builds both images and scans them with trivy |
| `make e2e` | brings up the Compose stack and runs Playwright with axe-core |
| `make docs` | `mkdocs build --strict` |

## Commits

- Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `test:`, `chore:`, `sec:`, `ci:`, `build:`, `refactor:`.
- Keep commits small. Each commit should pass `make ci` on its own.
- Sign off every commit under the [Developer Certificate of Origin](https://developercertificate.org/) with `git commit -s`. CI checks for the `Signed-off-by:` line on every commit in a pull request. There is no CLA.

## Tests

- Tests ship in the same change as the code they cover.
- For the evaluator, write the tests first.
- Every API route needs at least one allowed and one denied authorization test. `tests/integration/test_route_authz.py` fails if a route is missing from its table.
- Coverage must stay at or above 90 percent for `dsec_metrics.core` and 80 percent overall.

## Dependencies

Ask in an issue before adding a dependency that is not already in `pyproject.toml` or `web/package.json`. Prefer the standard library and the libraries already chosen. Every new dependency must be pinned in a lock file with hashes.

## Design decisions

Significant decisions are recorded as ADRs in `docs/adr/NNNN-title.md` with context, decision and consequences. Copy `docs/adr/template.md`. An ADR is changed by a later ADR that supersedes it, not by editing history.

## Milestone plans

Before code is written for a milestone, a plan goes in `docs/plans/mN.md` and is reviewed. If something is ambiguous, write the question in the plan instead of guessing.

## Reporting security issues

See [SECURITY.md](SECURITY.md). Do not open public issues for vulnerabilities.

## Code of conduct

Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).
