# syntax=docker/dockerfile:1
# Web image: Caddy serving the built front end and proxying /api.
# Final stage: distroless static, no shell, non-root.

FROM node:25-slim@sha256:81db02c4b671288a03915da9534dbd54f96d0e7c24d80ccc54f5b36b2e684370 AS build
ENV CI=1 COREPACK_ENABLE_DOWNLOAD_PROMPT=0
WORKDIR /web
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml web/.npmrc ./
# Optional build secret "build_ca": see app.Dockerfile.
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca; fi; \
    corepack enable pnpm && pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm run build

# Caddy is built from source (deploy/docker/caddy) with a current Go toolchain and
# patched dependencies; the upstream binary lags on Go security releases.
FROM golang:1.27.1-trixie@sha256:433790e515d27dc6003e847e644cc0af956985cf315c1c58a3b73ee2dd305183 AS caddy
ENV CGO_ENABLED=0 GOTOOLCHAIN=local GOFLAGS=-mod=readonly
WORKDIR /build
COPY deploy/docker/caddy/go.mod deploy/docker/caddy/go.sum deploy/docker/caddy/main.go ./
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca; fi; \
    go build -trimpath -ldflags "-s -w" -o /caddy . \
 && mkdir -p /rootfs/run/caddy \
 && chown -R 65532:65532 /rootfs/run/caddy

FROM gcr.io/distroless/static-debian13:nonroot@sha256:e2e927ec666bae08560abb3c55d0659eceabb657f56b6782ab500a9fc7f555e3

LABEL org.opencontainers.image.title="dsec-metrics-web" \
      org.opencontainers.image.description="dsec-metrics web front end and reverse proxy" \
      org.opencontainers.image.source="https://github.com/FlavioImbertDomingos/dsec-metrics" \
      org.opencontainers.image.licenses="Apache-2.0"

COPY --from=caddy /caddy /usr/bin/caddy
COPY --from=caddy /rootfs/ /
COPY deploy/docker/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /web/dist /srv

ENV XDG_CONFIG_HOME=/run/caddy/config \
    XDG_DATA_HOME=/run/caddy/data

USER 65532:65532
EXPOSE 8443
ENTRYPOINT ["/usr/bin/caddy"]
CMD ["run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
