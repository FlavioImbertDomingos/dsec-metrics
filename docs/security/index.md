# Security overview

This page is the entry point for a security reviewer. The full architecture document for enterprise reviews (`docs/security/architecture.md`) arrives in M5; until then, this page and the [threat model](threat-model.md) describe the system as built.

## Reporting a vulnerability

Use GitHub private vulnerability reporting on the repository's Security tab. See [SECURITY.md](https://github.com/FlavioImbertDomingos/dsec-metrics/blob/main/SECURITY.md).

## Controls in place after M0

| Area | Control | Where |
| --- | --- | --- |
| Authentication | Local accounts only in development mode; startup refuses production mode with local accounts | `config.py`, `tests/unit/test_config.py` |
| Authentication | Argon2id (RFC 9106 parameters), constant-time check for unknown users | `auth/passwords.py` |
| Sessions | Server-side, token hash only, 30-minute idle and 8-hour absolute limits, `__Host-` cookie with Secure, HttpOnly, SameSite=Strict | `auth/sessions.py` |
| CSRF | Synchronizer token plus `Origin` check on every unsafe request; sign-in also checks `Origin` | `api/policy.py` |
| Brute force | Throttle per username (5 in 15 minutes) and per source (20 in 15 minutes) | `auth/throttle.py` |
| Authorization | Deny by default; one policy module; CI fails if a route lacks a policy or an allowed and denied test | `api/policy.py`, `tests/integration/test_route_authz.py` |
| Input | Pydantic models with unknown fields rejected; validation errors never echo input | `api/schemas.py`, `api/app.py` |
| Transport | TLS 1.2+ at the edge with HSTS; TLS 1.3 with `verify-full` to Postgres; production mode refuses unverified database TLS | `Caddyfile`, `compose.yaml` |
| Browser | CSP with `script-src 'self'` and no inline scripts, `frame-ancestors 'none'`, COOP, CORP, `nosniff`, no referrer, restrictive Permissions-Policy | `deploy/docker/Caddyfile`, checked in `web/e2e/signin.spec.ts` |
| Containers | Distroless, no shell, non-root, read-only root filesystem, all capabilities dropped, `no-new-privileges`, memory and CPU limits | `deploy/docker/*.Dockerfile`, `compose.yaml` |
| Network | Only the web service publishes a port (loopback by default); the backend network has no outbound access; only the worker joins the `collectors` network, and collectors call only allowlisted hosts after an address check | `compose.yaml` |
| Secrets | Docker secrets as files, never environment variables; development CA key deleted after use | `scripts/dev-secrets.sh` |
| Supply chain | Hash-locked dependencies, one-week release cooldown, SHA-pinned actions, digest-pinned images, no install scripts in pnpm | `uv.lock`, `web/pnpm-workspace.yaml`, `.github/` |
| CI gates | ruff, mypy, eslint, tsc, bandit, semgrep, pip-audit, osv-scanner, gitleaks, zizmor, trivy | [ADR-0005](../adr/0005-security-gate-policy.md) |
| Release | cosign keyless signatures, CycloneDX SBOM attestation, SLSA provenance | `.github/workflows/release.yml` |

## Verifying a release image

```sh
cosign verify ghcr.io/flavioimbertdomingos/dsec-metrics:0.0.1-alpha.1 \
  --certificate-identity-regexp '^https://github.com/FlavioImbertDomingos/dsec-metrics/\.github/workflows/release\.yml@refs/tags/v' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com

gh attestation verify oci://ghcr.io/flavioimbertdomingos/dsec-metrics:0.0.1-alpha.1 \
  --owner FlavioImbertDomingos
```
