# Deployment with Docker Compose

Docker Compose is the supported deployment. One `.env` file and `docker compose up -d` bring up a TLS-protected install on a single Linux host.

!!! note "Draft"
    The brief refers to a "Deployment with Docker Compose" section that was not written yet. This page is the draft from M0. Production use waits for OIDC (M5); until then the stack runs in development mode with local accounts.

## Host requirements

- Linux x86_64 or arm64 with Docker Engine 25 or later and Compose v2
- 2 CPUs, 4 GB of memory and 20 GB of disk for the database volume
- Port 443 (or the port you choose) reachable from users' browsers
- No outbound internet access is needed at runtime

## Files

| File | Purpose |
| --- | --- |
| `compose.yaml` | Services, networks, hardening and secrets |
| `.env` | Your settings; copy from `.env.example` |
| `deploy/compose/secrets/` | Secret files mounted as Docker secrets |
| `compose.dev.yaml` | Development only: publishes Postgres on 127.0.0.1 |

## Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `DSEC_HOSTNAME` | `localhost` | Name users type in the browser; must match the web certificate |
| `DSEC_PUBLIC_ORIGIN` | `https://localhost` | Scheme, host and port as the browser sees them. Sign-in and CSRF checks compare against it |
| `DSEC_HTTPS_PORT` | `443` | Host port for HTTPS |
| `DSEC_BIND_ADDRESS` | `127.0.0.1` | Host interface for the web port. Set `0.0.0.0` (or a specific address) to serve other machines |
| `DSEC_MODE` | `development` in Compose, `production` in the application | `production` refuses local accounts and unverified database TLS |
| `DSEC_LOCAL_ACCOUNTS` | `true` in Compose | Development sign-in. Must be `false` in production |
| `DSEC_LOG_LEVEL` | `INFO` | Log level for all services |
| `DSEC_VERSION` | `dev` | Image tag |
| `DSEC_PULL_POLICY` | `build` | `build` builds from source; `missing` or `always` pulls signed release images |
| `DSEC_BUILD_CA_FILE` | unset | CA bundle for building behind a TLS-inspecting proxy (build time only) |

Session and throttle limits can be tuned with `DSEC_SESSION_IDLE_MINUTES`, `DSEC_SESSION_ABSOLUTE_HOURS`, `DSEC_LOGIN_WINDOW_MINUTES`, `DSEC_LOGIN_MAX_FAILURES_PER_USER` and `DSEC_LOGIN_MAX_FAILURES_PER_SOURCE`, added to the `environment` of the `api` service.

## Secrets and certificates

The stack reads these files from `deploy/compose/secrets/`:

| File | Used by | Contents |
| --- | --- | --- |
| `db_password` | postgres, api, worker, migrate | Database password |
| `dev_admin_password` | migrate | Password for `dev-admin` (development only) |
| `dev_ca.crt` | api, worker, migrate | CA that signed the Postgres certificate |
| `db_tls.crt`, `db_tls.key` | postgres | Postgres server certificate, SAN `postgres` |
| `web_tls.crt`, `web_tls.key` | web | Certificate users see, SAN `DSEC_HOSTNAME` |
| `report_signing_key` | api, worker | Ed25519 private key that signs evidence packages |

For development, `make dev-secrets` creates all of them. For a shared or production host:

1. Issue the web certificate from your company CA for the real host name, with the full chain in `web_tls.crt`.
2. Issue the Postgres certificate from an internal CA (SAN `postgres`) and put that CA in `dev_ca.crt`. The file name stays the same in M0; it becomes `db_ca.crt` in M5.
3. Generate the database password with at least 32 random characters.
4. Create the report signing key once with `dsec-metrics keys generate --private-key report_signing_key --public-key report_signing_key.pub` (or `openssl genpkey -algorithm ed25519` with OpenSSL 3), keep an offline backup, and give auditors the fingerprint that `keys generate` prints. See [Reports](../reports.md#the-signing-key).
5. Keep the directory owned by root with mode 700. The files must stay readable by UID 999 (Postgres) and UID 65532 (app and Caddy); mode 644 inside the 700 directory does that.

## Start, stop, upgrade

```sh
docker compose up -d --wait     # start and wait for health checks
docker compose ps               # health of each service
docker compose logs -f api      # JSON logs, ready for your SIEM
docker compose down             # stop; the database volume stays
```

Upgrading: pull or build the new images, then `docker compose up -d --wait`. The `migrate` service applies database migrations before the API and worker start.

Verify release images before running them (see the [security overview](../security/index.md#verifying-a-release-image)).

## Backups

The database is the only state. Back it up with `pg_dump` through the container:

```sh
docker compose exec -T postgres pg_dump -U dsec -d dsec -Fc > dsec-$(date +%F).dump
```

Restore into an empty volume with `pg_restore`. Evidence retention and purge jobs arrive with M1 and M3.

## Air-gapped hosts

The running stack makes no outbound calls. To install without internet access, on a connected machine run `docker save` for the two images and `postgres:16`, copy the archives, `docker load` them on the target host, set `DSEC_PULL_POLICY=missing`, and start the stack. The full air-gapped guide, including offline signature verification, arrives in M5.

## Building behind a TLS-inspecting proxy

If your network re-signs HTTPS traffic, builds fail to download Python or npm packages. Point `DSEC_BUILD_CA_FILE` at your proxy's CA bundle:

```sh
DSEC_BUILD_CA_FILE=/path/to/corporate-ca.pem docker compose build
```

The bundle is passed as a BuildKit secret. It is used only while dependencies download and is not stored in any image layer.

## Hardening already applied

Every service runs with a read-only root filesystem, `no-new-privileges`, all Linux capabilities dropped (Postgres keeps the five its entrypoint needs), memory and CPU limits, and log rotation. The API, worker and database sit on an internal network with no route to the internet. Details are in [ADR-0002](../adr/0002-container-base-images.md) and [ADR-0003](../adr/0003-compose-topology.md).
