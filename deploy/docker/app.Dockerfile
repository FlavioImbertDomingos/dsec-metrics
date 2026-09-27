# syntax=docker/dockerfile:1
# Application image: API, worker, migrations and CLI, selected by command.
# Final stage: distroless, no shell, non-root, Python from python-build-standalone.

FROM ghcr.io/astral-sh/uv:0.12.19-trixie-slim@sha256:c40e42de0e1516439b5139d7a214657dbffbbd3d2366661347efae7b8337c197 AS build

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_FROZEN=1 \
    UV_NO_DEV=1 \
    UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_PYTHON_PREFERENCE=only-managed \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# Optional build secret "build_ca": a CA bundle for building behind a TLS-inspecting
# proxy. Empty or absent means the default trust store. It never reaches the image.
WORKDIR /src
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca; fi; \
    uv python install 3.12

# Dependencies first, so source changes do not rebuild this layer.
COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca; fi; \
    uv sync --no-default-groups --no-install-project

COPY src ./src
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca; fi; \
    uv sync --no-default-groups --no-editable \
 && install -d -o 65532 -g 65532 -m 0700 /rootfs/run/dsec

# The runtime never installs packages. Remove pip and ensurepip from the interpreter so
# their vendored libraries are not shipped (or scanned) at all.
RUN set -eu; for py in /opt/python/cpython-3.12*; do \
      rm -rf "$py"/lib/python3.12/site-packages/pip "$py"/lib/python3.12/site-packages/pip-* \
             "$py"/lib/python3.12/ensurepip "$py"/bin/pip*; \
    done

FROM gcr.io/distroless/cc-debian13:nonroot@sha256:54df941ed0d06a1bd95ef5e0ce391fd8d9f94b64782dc9a60062727849ee3f97

LABEL org.opencontainers.image.title="dsec-metrics" \
      org.opencontainers.image.description="dsec-metrics API, worker and CLI" \
      org.opencontainers.image.source="https://github.com/FlavioImbertDomingos/dsec-metrics" \
      org.opencontainers.image.licenses="Apache-2.0"

COPY --from=build /opt/python /opt/python
COPY --from=build /app/.venv /app/.venv
COPY --from=build /rootfs/ /

ENV PATH=/app/.venv/bin:/usr/bin:/bin \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER 65532:65532
WORKDIR /app
EXPOSE 8000
ENTRYPOINT ["/app/.venv/bin/dsec-metrics"]
CMD ["serve", "api", "--host", "0.0.0.0"]
