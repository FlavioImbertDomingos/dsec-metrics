# syntax=docker/dockerfile:1
# Web image: Caddy serving the built front end and proxying /api.
# Final stage: distroless static, no shell, non-root.

FROM node:24-slim@sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6 AS build
ENV CI=1 COREPACK_ENABLE_DOWNLOAD_PROMPT=0
WORKDIR /web
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml web/.npmrc ./
# Optional build secret "build_ca": see app.Dockerfile.
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca; fi; \
    corepack enable pnpm && pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm run build

FROM caddy:2.11.4@sha256:0c994536bddb66445885237f1a5dcc1916bccea922661c76b4e9fc24061f9b52 AS caddy
# A plain copy drops the file capability (cap_net_bind_service) the upstream image sets.
# We listen on 8443 and run with all capabilities dropped, so it is not needed.
RUN cp /usr/bin/caddy /caddy \
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
