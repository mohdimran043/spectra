# ===========================================================================
# SPECTRA - developer entry points.
#
#   make              list every target
#   make install      local virtualenv, no Docker
#   make up           full containerised stack
#   make package-release   sealed offline bundle for an operator
#
# APP_VERSION is exported from ./VERSION and is the single source of truth for
# every image tag.  Every target here has a plain-command equivalent documented
# in docs/deployment.md - Make is a convenience, never a requirement.
#
# NOTE: release bundles deliberately ship NO Makefile.  Operators call
# ./scripts/<name>.sh directly.
# ===========================================================================

SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

APP_VERSION := $(shell tr -d '[:space:]' < VERSION)
export APP_VERSION

REPO_ROOT    := $(shell pwd)
VENV         := $(REPO_ROOT)/.venv
PY           := $(VENV)/bin/python
PIP          := $(VENV)/bin/pip
SPECTRA      := $(VENV)/bin/spectra

DEV_COMPOSE  := deploy/docker-compose.yml
GPU_COMPOSE  := deploy/docker-compose.gpu.yml
LAN_COMPOSE  := deploy/docker-compose.lan.yml

# make up GPU=1  adds the NVIDIA overlay.  See docs/deployment.md for why this
# is an overlay file rather than a compose profile.
ifeq ($(GPU),1)
COMPOSE_FILES := -f $(DEV_COMPOSE) -f $(GPU_COMPOSE)
else
COMPOSE_FILES := -f $(DEV_COMPOSE)
endif

COMPOSE := docker compose $(COMPOSE_FILES)

.PHONY: help install install-ml install-backends up start down restart logs ps \
        seed-demo ingest reindex demo db-migrate verify state \
        test lint format benchmark gpu-check model-health \
        version-bump sync-deploy-env package-release package-patch \
        compose-validate audit clean

# ---------------------------------------------------------------------------
help:  ## Show this help
	@printf '\nSPECTRA $(APP_VERSION)\n\n'
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "} {printf "  \033[1m%-22s\033[0m %s\n", $$1, $$2}'
	@printf '\nVariables:  GPU=1  SRC=<path>  V=patch|minor|major  SVC="api worker"  DB=1  UI=1\n'
	@printf 'Every target has a plain-command equivalent in docs/deployment.md\n\n'

# --- local development -----------------------------------------------------
install:  ## Create .venv and install the monorepo (no Docker needed)
	./scripts/bootstrap.sh

install-ml:  ## Install the heavy [ml] extra into .venv
	./scripts/bootstrap.sh --ml

install-backends:  ## Install the [backends] extra into .venv
	./scripts/bootstrap.sh --backends

# --- containerised stack ---------------------------------------------------
up:  ## Build and start the full dev stack (GPU=1 for NVIDIA)
	$(COMPOSE) up -d --build
	@printf '\n  frontend        http://localhost:3000\n'
	@printf '  enterprise app  http://localhost:3001\n'
	@printf '  api             http://localhost:8000/api/health\n\n'
	@printf '  next: make db-migrate && make seed-demo\n'

start: up  ## Alias for up

down:  ## Stop the dev stack (volumes are kept)
	$(COMPOSE) down

restart:  ## Recreate the application services only
	$(COMPOSE) up -d --force-recreate --no-deps api worker frontend mock-enterprise

logs:  ## Follow logs (make logs S=api for one service)
	$(COMPOSE) logs -f --tail 200 $(S)

ps:  ## Show container status
	$(COMPOSE) ps

db-migrate:  ## Apply baseline + migrations to the dev stack
	SPECTRA_COMPOSE_FILE=$(REPO_ROOT)/$(DEV_COMPOSE) \
	SPECTRA_ENV_FILE=$(REPO_ROOT)/deploy/.env \
		./deploy/scripts/run-migrations.sh

verify:  ## Probe the API and every datastore
	SPECTRA_COMPOSE_FILE=$(REPO_ROOT)/$(DEV_COMPOSE) \
	SPECTRA_ENV_FILE=$(REPO_ROOT)/deploy/.env \
		./deploy/scripts/verify-deployment.sh

state:  ## Show what is deployed
	SPECTRA_COMPOSE_FILE=$(REPO_ROOT)/$(DEV_COMPOSE) \
	SPECTRA_ENV_FILE=$(REPO_ROOT)/deploy/.env \
		./deploy/scripts/show-state.sh

# --- data ------------------------------------------------------------------
seed-demo:  ## Load the demo corpus and demo database rows
	$(SPECTRA) seed-demo

ingest:  ## Ingest a folder: make ingest SRC=./demo-data
	@test -n "$(SRC)" || { printf 'set SRC=<path>, e.g. make ingest SRC=./demo-data\n' >&2; exit 1; }
	$(SPECTRA) ingest $(SRC)

reindex:  ## Rebuild vector, lexical and graph indexes from the control plane
	$(SPECTRA) reindex

demo:  ## Reproducible end-to-end demonstration
	$(SPECTRA) demo

# --- quality ---------------------------------------------------------------
test:  ## Run the test suite with coverage
	./scripts/test.sh $(ARGS)

lint:  ## Check formatting and lint rules
	./scripts/lint.sh

format:  ## Apply formatting and safe lint fixes
	./scripts/lint.sh --fix

benchmark:  ## Run the evaluation harness
	$(PY) -m spectra_eval

gpu-check:  ## Report GPU, driver and container-runtime readiness
	./scripts/gpu-check.sh

model-health:  ## Report model registry, load state and VRAM
	./scripts/model-health.sh

# --- release engineering ---------------------------------------------------
version-bump:  ## Bump VERSION: make version-bump V=patch|minor|major
	@test -n "$(V)" || { printf 'set V=patch|minor|major\n' >&2; exit 1; }
	@current=$$(tr -d '[:space:]' < VERSION); \
	major=$${current%%.*}; rest=$${current#*.}; minor=$${rest%%.*}; patch=$${rest#*.}; \
	case "$(V)" in \
		major) major=$$((major+1)); minor=0; patch=0 ;; \
		minor) minor=$$((minor+1)); patch=0 ;; \
		patch) patch=$$((patch+1)) ;; \
		*) printf 'V must be patch, minor or major\n' >&2; exit 1 ;; \
	esac; \
	next="$$major.$$minor.$$patch"; \
	printf '%s\n' "$$next" > VERSION; \
	printf 'VERSION %s -> %s\n' "$$current" "$$next"; \
	printf 'next: add a CHANGELOG.md entry, then make sync-deploy-env\n'

sync-deploy-env:  ## Align APP_VERSION in deploy/.env and .env.example with VERSION
	@version=$$(tr -d '[:space:]' < VERSION); \
	for f in deploy/.env deploy/.env.example; do \
		[ -f "$$f" ] || continue; \
		sed -i -E "s|^[[:space:]]*APP_VERSION=.*$$|APP_VERSION=$$version|" "$$f"; \
		printf '  %s -> APP_VERSION=%s\n' "$$f" "$$version"; \
	done

package-release:  ## Build a sealed offline release bundle
	./scripts/package-release.sh

package-patch:  ## Build a patch bundle: make package-patch SVC='api worker' [DB=1] [UI=1]
	SVC="$(SVC)" DB="$(DB)" UI="$(UI)" ./scripts/package-patch.sh

compose-validate:  ## Validate both compose files
	docker compose -f $(DEV_COMPOSE) config -q && printf '  dev compose OK\n'
	APP_VERSION=$(APP_VERSION) APP_ROOT=/tmp/spectra-validate \
		docker compose -f $(LAN_COMPOSE) config -q && printf '  LAN compose OK\n'

audit:  ## Run the offline-bundle invariants audit
	@test -f VERSION && printf 'VERSION: OK\n'
	@! grep -q 'build:' $(LAN_COMPOSE) && printf 'LAN compose has no build: OK\n'
	@! grep -qE 'image:.*:latest' $(LAN_COMPOSE) && printf 'no latest tags: OK\n'
	@! grep -q '^version:' $(LAN_COMPOSE) && printf 'no version key: OK\n'
	@test -d db/baseline && test -d db/migrations && printf 'db split: OK\n'
	@test -x scripts/package-release.sh && test -x deploy/scripts/deploy.sh && printf 'scripts executable: OK\n'
	@printf 'CHANGE_ME placeholders in deploy/.env.example: '; grep -c CHANGE_ME deploy/.env.example

clean:  ## Remove build artefacts and caches (never touches data/ or models/)
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage
	@printf '  caches cleared (data/, models/ and releases/ untouched)\n'
