# 0003: Compose topology, TLS and the reverse proxy

- Status: accepted
- Date: 2026-09-26
- Deciders: maintainers

## Context

The brief lists api, worker, web and postgres as Compose services and says Caddy serves the built front end and routes `/api`. It requires TLS for every connection and names `compose.yaml` in one place and `deploy/compose/docker-compose.yml` in another. M0 review chose `compose.yaml` at the root (plan question 4), Caddy as the `web` service (question 6), one app image (question 7) and TLS to Postgres from M0 (question 12).

## Decision

- `compose.yaml` at the repository root. `deploy/compose/` holds secrets and, later, variants.
- Services: `postgres`, `migrate` (one-shot: migrations and dev admin), `api`, `worker`, `web` (Caddy with the built UI).
- Two networks. `edge` holds `web` only. `backend` is `internal: true` and holds `web`, `api`, `worker` and `postgres`, so nothing on it can reach the internet.
- Only `web` publishes a port, on `127.0.0.1:443` by default (`DSEC_BIND_ADDRESS`, `DSEC_HTTPS_PORT`).
- `make dev-secrets` creates a development CA that signs both the Caddy certificate and the Postgres certificate. The CA is name-constrained, valid for one year, and its private key is deleted after signing. This replaces Caddy's `tls internal` from the plan, so there is one root to trust.
- Postgres accepts only `hostssl` connections with SCRAM, minimum TLS 1.3. The app connects with `sslmode=verify-full`, and production mode refuses anything weaker.
- Caddy sets HSTS, a CSP with no `unsafe-inline`, COOP, CORP, `nosniff`, `no-referrer`, a restrictive Permissions-Policy and `frame-ancestors 'none'`, strips `Server` and `Via`, and limits `/api` request bodies to 1 MB.
- Secrets are Docker secrets (files). The secrets directory is mode 700 and the files 644, because the containers run as different users (Postgres as 999, the app and Caddy as 65532).

## Consequences

- The Caddy-to-API hop is plain HTTP on the internal network. The threat model records it (T4); M5 evaluates mTLS or a Unix socket.
- Collectors in M4 need outbound access. They will get a separate network with an egress allowlist rather than opening `backend`.
- Production deployments need their own certificates and secret files with tighter ownership. The deployment guide covers this.
