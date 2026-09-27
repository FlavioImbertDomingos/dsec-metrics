# dsec-metrics developer tasks. `make ci` runs the same checks as GitHub Actions.
#
# Scanner tools run from digest-pinned container images so local and CI results match.
# Behind a TLS-inspecting proxy, set DSEC_BUILD_CA_FILE to your proxy's CA bundle; it is
# used for image builds and mounted into scanner containers. It never enters an image.

SHELL := /bin/sh
.DEFAULT_GOAL := help

UV ?= uv
PNPM ?= pnpm
DOCKER ?= docker
COMPOSE ?= $(DOCKER) compose

TRIVY_IMAGE := ghcr.io/aquasecurity/trivy:0.74.0@sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969
GITLEAKS_IMAGE := ghcr.io/gitleaks/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f
OSV_IMAGE := ghcr.io/google/osv-scanner:v2.6.0@sha256:afd838850ac1a0fcc15ff4a041dc9ba11123c3f0d2666217a5f0fcf9222b55fa
SEMGREP_IMAGE := semgrep/semgrep:1.178.0@sha256:32e459968daabe7ab86968184a29109b9564aa00392401156f9788452b42786b

APP_IMAGE := ghcr.io/flavioimbertdomingos/dsec-metrics:dev
WEB_IMAGE := ghcr.io/flavioimbertdomingos/dsec-metrics-web:dev

SEMGREP_RULES := --config p/owasp-top-ten --config p/python --config p/typescript \
	--config p/react --config p/dockerfile --config p/secrets

CA_FILE := $(DSEC_BUILD_CA_FILE)
ifneq ($(strip $(CA_FILE)),)
CA_MOUNT := -v $(abspath $(CA_FILE)):/etc/dsec-extra-ca.pem:ro \
	-e SSL_CERT_FILE=/etc/dsec-extra-ca.pem -e REQUESTS_CA_BUNDLE=/etc/dsec-extra-ca.pem
endif
TOOL := $(DOCKER) run --rm -v "$(CURDIR)":/src -w /src $(CA_MOUNT)

.PHONY: help
help: ## List targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-z0-9-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: setup
setup: ## Install Python and web dependencies from the lock files
	$(UV) sync --frozen
	cd web && $(PNPM) install --frozen-lockfile

.PHONY: dev-secrets signing-key
dev-secrets: ## Create local passwords, a development CA and a report signing key (once)
	sh scripts/dev-secrets.sh

signing-key: ## Create the report signing key with the app image (when dev-secrets could not)
	$(COMPOSE) run --rm --no-deps --user "$$(id -u):$$(id -g)" \
		-v "$(CURDIR)/deploy/compose/secrets:/out" api \
		keys generate --private-key /out/report_signing_key \
		--public-key /out/report_signing_key.pub
	chmod 644 deploy/compose/secrets/report_signing_key
	$(COMPOSE) up -d --wait api worker

## ---- lint -------------------------------------------------------------------

.PHONY: lint lint-python lint-web
lint: lint-python lint-web ## ruff, mypy, eslint, tsc, prettier

lint-python:
	$(UV) run --frozen ruff check .
	$(UV) run --frozen ruff format --check .
	$(UV) run --frozen mypy

lint-web:
	cd web && $(PNPM) run lint && $(PNPM) run typecheck && $(PNPM) run format:check

## ---- test -------------------------------------------------------------------

.PHONY: test test-python test-web
test: test-python test-web ## pytest (Postgres via Testcontainers) and Vitest, with coverage gates

test-python:
	$(UV) run --frozen pytest --cov --cov-report=term --cov-report=json:reports/coverage.json
	$(UV) run --frozen python scripts/coverage_gates.py reports/coverage.json

test-web:
	cd web && $(PNPM) run test:coverage

## ---- scan -------------------------------------------------------------------

.PHONY: scan bandit semgrep pip-audit osv gitleaks zizmor suppressions
scan: bandit semgrep pip-audit osv gitleaks zizmor suppressions ## SAST, dependency, secret and workflow scans

bandit:
	$(UV) run --frozen bandit -c pyproject.toml -r src --severity-level medium --confidence-level medium -q

semgrep:
	$(TOOL) $(SEMGREP_IMAGE) semgrep scan --metrics=off --disable-version-check \
		$(SEMGREP_RULES) --severity ERROR --error --quiet

pip-audit: reports
	$(UV) export --frozen --all-groups --no-emit-project --format requirements-txt -q \
		-o reports/requirements-all.txt
	$(UV) run --frozen pip-audit -r reports/requirements-all.txt --require-hashes --disable-pip \
		--progress-spinner off

osv:
	$(TOOL) $(OSV_IMAGE) scan source --config osv-scanner.toml \
		-L uv.lock -L web/pnpm-lock.yaml -L deploy/docker/caddy/go.mod

gitleaks:
	$(TOOL) --user "$$(id -u):$$(id -g)" $(GITLEAKS_IMAGE) git --redact --no-banner \
		--config .gitleaks.toml /src

zizmor:
	$(UV) run --frozen zizmor --min-severity medium $(if $(GH_TOKEN),,--offline) .github/

suppressions: ## List every active scanner suppression
	@sh scripts/list-suppressions.sh

## ---- images -----------------------------------------------------------------

.PHONY: images image-scan sbom
images: reports ## Build both images, scan them and the Dockerfiles with trivy, write SBOMs
	DSEC_BUILD_CA_FILE="$(CA_FILE)" $(COMPOSE) build
	$(MAKE) image-scan sbom

image-scan:
	$(DOCKER) save -o reports/app-image.tar $(APP_IMAGE)
	$(DOCKER) save -o reports/web-image.tar $(WEB_IMAGE)
	$(TOOL) -v dsec-trivy-cache:/root/.cache $(TRIVY_IMAGE) image --input reports/app-image.tar \
		--ignorefile .trivyignore.yaml --severity HIGH,CRITICAL --exit-code 1 --no-progress
	$(TOOL) -v dsec-trivy-cache:/root/.cache $(TRIVY_IMAGE) image --input reports/web-image.tar \
		--ignorefile .trivyignore.yaml --severity HIGH,CRITICAL --exit-code 1 --no-progress
	$(TOOL) -v dsec-trivy-cache:/root/.cache $(TRIVY_IMAGE) config --severity HIGH,CRITICAL \
		--exit-code 1 deploy/docker

sbom:
	$(TOOL) -v dsec-trivy-cache:/root/.cache $(TRIVY_IMAGE) image --input reports/app-image.tar \
		--format cyclonedx --output reports/dsec-metrics.cdx.json --no-progress
	$(TOOL) -v dsec-trivy-cache:/root/.cache $(TRIVY_IMAGE) image --input reports/web-image.tar \
		--format cyclonedx --output reports/dsec-metrics-web.cdx.json --no-progress

## ---- run and e2e ------------------------------------------------------------

.PHONY: up down demo e2e screenshot
up: ## Start the Compose stack and wait until it is healthy
	DSEC_BUILD_CA_FILE="$(CA_FILE)" $(COMPOSE) up -d --build --wait

down: ## Stop the stack (keeps the database volume)
	$(COMPOSE) down

demo: up ## Load 12 months of sample data into the running stack
	$(COMPOSE) exec -T api dsec-metrics demo > /dev/null

e2e: demo ## Playwright and axe-core against the running stack with sample data
	$(COMPOSE) exec -T api dsec-metrics users grant-auditor e2e-auditor \
		--framework pci-dss-4.0.1 --period-start 2026-01-01 --period-end 2026-12-31 \
		--days 1 --password-file - < deploy/compose/secrets/dev_admin_password > /dev/null
	cd web && $(PNPM) run e2e

screenshot: demo ## Regenerate docs/assets/screenshot.png
	cd web && node e2e/screenshot.js

## ---- local development with reload -----------------------------------------

.PHONY: dev-db dev-api dev-web
dev-db: ## Postgres only, published on 127.0.0.1:5432, migrated, with the dev admin
	DSEC_BUILD_CA_FILE="$(CA_FILE)" $(COMPOSE) -f compose.yaml -f compose.dev.yaml up -d --wait postgres migrate

dev-api: ## API on the host with reload (run dev-db first)
	DSEC_MODE=development DSEC_LOCAL_ACCOUNTS=true DSEC_PUBLIC_ORIGIN=http://localhost:5173 \
	DSEC_DB_HOST=localhost DSEC_DB_PASSWORD_FILE=deploy/compose/secrets/db_password \
	DSEC_DB_SSLROOTCERT=deploy/compose/secrets/dev_ca.crt \
	DSEC_WORKER_HEARTBEAT_FILE=/tmp/dsec-dev-heartbeat \
	$(UV) run --frozen uvicorn dsec_metrics.api.app:app_factory --factory --reload \
		--host 127.0.0.1 --port 8000

dev-web: ## Vite dev server on http://localhost:5173, proxying /api to dev-api
	cd web && $(PNPM) run dev

## ---- docs -------------------------------------------------------------------

.PHONY: docs
docs: ## Build the docs site with warnings as errors
	$(UV) run --frozen mkdocs build --strict --site-dir site

## ---- everything -------------------------------------------------------------

.PHONY: ci
ci: lint test scan images e2e docs ## Run every CI job locally
	@echo "make ci: all jobs passed"

reports:
	@mkdir -p reports

.PHONY: clean
clean: ## Remove build and test outputs
	rm -rf reports site web/dist web/coverage web/test-results web/playwright-report \
		.coverage coverage.json htmlcov
