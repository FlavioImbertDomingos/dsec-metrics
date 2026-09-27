# 0002: Container base images and the no-shell rule

- Status: accepted
- Date: 2026-09-26
- Deciders: maintainers

## Context

The brief requires non-root containers with a read-only root filesystem, dropped capabilities and no shell in the final image. It also requires Python 3.12. `gcr.io/distroless/python3` ships the Debian system Python, which is not 3.12. Chainguard's free images publish only the `latest` tag, so Python cannot be pinned to 3.12 there.

## Decision

- App image (`dsec-metrics`: API, worker, migrations, CLI): uv installs a python-build-standalone CPython 3.12 and the locked virtual environment in a build stage; the final stage copies both onto `gcr.io/distroless/cc-debian13:nonroot`. The command selects the component.
- Web image (`dsec-metrics-web`): the front end is built in a `node:24-slim` stage. Caddy is built from source in a `golang` stage from `deploy/docker/caddy/` (Caddy v2.11.4 with the standard modules) and copied onto `gcr.io/distroless/static-debian13:nonroot`. Caddy listens on 8443 and needs no capabilities.
- Why Caddy is built from source: the plan copied the binary from the official Caddy image, but that binary was built with Go 1.26.3 and older `x/crypto`, `x/net`, `x/text` and `grpc` modules, and trivy reported 17 high findings in it. Building with Go 1.26.8 and upgraded modules clears them. `go.mod` and `go.sum` pin every module, and Dependabot (`gomod`) proposes updates weekly.
- Every base image is pinned by digest. Dependabot proposes digest updates weekly.
- Health checks run the application binary in exec form (`dsec-metrics health api`), since there is no shell or curl.
- An optional BuildKit secret, `build_ca`, carries a CA bundle for builds behind TLS-inspecting proxies. It is mounted only during `RUN` steps and never lands in a layer.

## Consequences

- Debugging inside a running container needs `docker debug` or an ephemeral debug container; `docker exec sh` does not work. That is the intent.
- WeasyPrint (M3) needs Pango, HarfBuzz and fontconfig, which distroless does not have. M3 will probably need a separate renderer image or a larger base; this ADR is revisited then.
- Distroless has no FIPS variant. The M5 FIPS documentation will describe a second build path (for example a UBI-based image), not a change of default.
- Postgres uses the official image, pinned by digest. It has a shell, runs its entrypoint as root and drops to the `postgres` user, so it keeps five capabilities (`CHOWN`, `DAC_OVERRIDE`, `FOWNER`, `SETGID`, `SETUID`).
