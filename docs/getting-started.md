# Getting started

## Requirements

- Docker Engine with Compose v2 (Docker Desktop works on macOS and Windows)
- `make` and `openssl` (both ship with macOS and most Linux distributions)
- Port 443 free on 127.0.0.1

## Run the stack

```sh
git clone https://github.com/FlavioImbertDomingos/dsec-metrics.git && cd dsec-metrics
make dev-secrets
docker compose up -d --wait
```

`make dev-secrets` writes random passwords and a development CA into `deploy/compose/secrets/`, a directory only your user can open. It prints the dev admin password once; the password is also in `deploy/compose/secrets/dev_admin_password`.

Open <https://localhost> and sign in as `dev-admin`.

## The certificate warning

The stack serves a certificate signed by the development CA that `make dev-secrets` created. You have two options:

- Accept the browser warning for `localhost`.
- Trust `deploy/compose/secrets/dev_ca.crt`. On macOS: `sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain deploy/compose/secrets/dev_ca.crt`. On Debian or Ubuntu: copy it to `/usr/local/share/ca-certificates/dsec-dev-ca.crt` and run `sudo update-ca-certificates`.

The CA is name-constrained to `localhost`, `postgres`, `127.0.0.1` and your `DSEC_HOSTNAME`, it expires after a year, and its private key is deleted as soon as it has signed the two certificates. Trusting it cannot let anyone issue certificates for other names.

## What is running

| Service | What it does |
| --- | --- |
| `web` | Caddy: TLS, security headers, the built front end, and a proxy for `/api` |
| `api` | FastAPI on the internal network only |
| `worker` | Background process; in M0 it checks the database and purges expired sessions |
| `migrate` | Runs database migrations and creates the dev admin, then exits |
| `postgres` | PostgreSQL 16, reachable only over TLS on the internal network |

`docker compose ps` shows their health. `docker compose logs -f api` follows the API's JSON log.

## Stop and reset

```sh
docker compose down        # stop, keep the database
docker compose down -v     # stop and delete the database volume
FORCE=1 make dev-secrets   # replace all passwords and certificates
```

## Working on the code

See [CONTRIBUTING.md](https://github.com/FlavioImbertDomingos/dsec-metrics/blob/main/CONTRIBUTING.md). In short: `make setup` installs dependencies, `make dev-db` starts Postgres alone, `make dev-api` and `make dev-web` run the API and the Vite dev server with reload, and `make ci` runs every CI job locally.
