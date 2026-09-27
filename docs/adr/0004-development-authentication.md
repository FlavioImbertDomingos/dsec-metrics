# 0004: Development authentication and server-side sessions

- Status: accepted
- Date: 2026-09-26
- Deciders: maintainers

## Context

M0 needs a signed-in placeholder page before OIDC exists (M5). The brief allows local accounts only in development mode, hashed with Argon2id, and requires the app to refuse production mode with local accounts. It requires short-lived sessions, Secure HttpOnly SameSite cookies and CSRF protection. The plan chose to build the real session and CSRF design now so later milestones inherit it (question 11).

## Decision

- `DSEC_MODE` defaults to `production`. `validate_startup` refuses production with `DSEC_LOCAL_ACCOUNTS=true`, with a non-https public origin, or with database TLS below `verify-ca`. The API, worker and CLI all call it.
- Passwords: argon2-cffi defaults (Argon2id, t=3, m=64 MiB, p=4). Unknown usernames are checked against a dummy hash so timing does not reveal which accounts exist. Minimum length 12.
- Sessions are rows in Postgres. The cookie `__Host-dsec_session` holds a 256-bit random token; the database stores only its SHA-256. Idle timeout 30 minutes, absolute limit 8 hours, both configurable. The worker purges expired rows.
- CSRF: a per-session synchronizer token, returned by `/api/me` and sign-in, must be sent as `X-CSRF-Token` on unsafe methods, and `Origin` must equal `DSEC_PUBLIC_ORIGIN`. Sign-in checks `Origin` as well.
- Throttling: 5 failures per username or 20 per source address within 15 minutes returns 429. Failures are stored in Postgres (no Redis).
- Authorization goes through `api/policy.py`. Each route declares exactly one policy (`public(reason)` or `authenticated`); roles arrive in M5. `tests/integration/test_route_authz.py` fails if a route has no policy or no allowed and denied case.

## Consequences

- The session and CSRF design stays when OIDC replaces local passwords; only the sign-in route changes.
- The throttle can lock out a known username for 15 minutes. Acceptable for development accounts.
- `uvicorn` trusts forwarding headers from any peer because the API is reachable only on the internal network. If the API is ever exposed directly, this setting must change; the threat model tracks it.
