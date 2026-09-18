# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# SPECTRA API image (and, via `--target worker`, the worker image).
#
#   docker build -f services/api/Dockerfile -t spectra-api:1.0.0 .
#   docker build -f services/api/Dockerfile --target worker -t spectra-worker:1.0.0 .
#
# Build context is the repository ROOT (the monorepo installs as one distribution).
# No secrets are ever baked in: every setting arrives as an environment variable
# at run time.
# ---------------------------------------------------------------------------

ARG PYTHON_VERSION=3.12

# =========================== stage: base ===================================
# Runtime OS layer shared by the builder and the final images.
FROM python:${PYTHON_VERSION}-slim AS base

ARG DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"

# ffmpeg      - audio/video decoding for the media pipelines
# libmagic1   - content-type sniffing during ingestion
# poppler-utils / tesseract-ocr - document + OCR extraction
# curl        - container healthchecks
# procps      - pgrep, used by the worker healthcheck
RUN apt-get update && apt-get install --no-install-recommends -y \
        ffmpeg \
        libmagic1 \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-eng \
        curl \
        procps \
        ca-certificates \
    && apt-get clean && find /var/lib/apt/lists -mindepth 1 -delete

# ========================== stage: builder =================================
# Compiles wheels into a self-contained virtualenv that the runtime copies.
FROM base AS builder

ARG INSTALL_ML=0
ARG INSTALL_BACKENDS=1

RUN apt-get update && apt-get install --no-install-recommends -y \
        build-essential \
        git \
    && apt-get clean && find /var/lib/apt/lists -mindepth 1 -delete

RUN python -m venv "${VIRTUAL_ENV}" && pip install --upgrade pip setuptools wheel

WORKDIR /src

# Project metadata first so dependency resolution caches independently of code.
COPY pyproject.toml ./
COPY README.md* ./

# The monorepo is one distribution; setuptools discovers packages under these roots.
COPY packages ./packages
COPY services ./services
COPY evaluation ./evaluation

# `readme = "README.md"` is declared in pyproject; keep the build working in
# contexts where the root README has not landed yet.
RUN [ -f README.md ] || printf '# SPECTRA\n' > README.md

# Deliberately no `RUN --mount=type=cache`: that is BuildKit-only syntax and
# hard-fails on the legacy builder ("the --mount option requires BuildKit"),
# which some offline build hosts still run.  Layer caching covers the common
# case; PIP_NO_CACHE_DIR keeps the image small either way.
RUN EXTRAS=""; \
    if [ "${INSTALL_BACKENDS}" = "1" ]; then EXTRAS="backends"; fi; \
    if [ "${INSTALL_ML}" = "1" ]; then \
        if [ -n "${EXTRAS}" ]; then EXTRAS="${EXTRAS},ml"; else EXTRAS="ml"; fi; \
    fi; \
    if [ -n "${EXTRAS}" ]; then \
        echo "installing spectra[${EXTRAS}]"; pip install ".[${EXTRAS}]"; \
    else \
        echo "installing spectra (core only)"; pip install .; \
    fi

# ========================== stage: runtime =================================
# The API image.
FROM base AS runtime

ARG APP_UID=10001
ARG APP_GID=10001
ARG APP_USER=spectra

# Non-root from here on.  /app is owned by the app user so runtime-created
# directories (data/runtime, data/objects, ...) succeed without root.
RUN groupadd --gid "${APP_GID}" "${APP_USER}" \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home --shell /usr/sbin/nologin "${APP_USER}" \
    && mkdir -p /app/data /app/models \
    && chown -R "${APP_UID}:${APP_GID}" /app

COPY --from=builder --chown=${APP_UID}:${APP_GID} /opt/venv /opt/venv

WORKDIR /app

# Source is copied (not just installed) so relative resources and REPO_ROOT
# path resolution inside spectra_config.settings behave as they do in dev.
COPY --chown=${APP_UID}:${APP_GID} pyproject.toml ./
COPY --chown=${APP_UID}:${APP_GID} packages ./packages
COPY --chown=${APP_UID}:${APP_GID} services ./services
COPY --chown=${APP_UID}:${APP_GID} evaluation ./evaluation

ENV DATA_DIR=/app/data \
    MODEL_DIR=/app/models \
    API_HOST=0.0.0.0 \
    API_PORT=8000 \
    SPECTRA_ROLE=api

USER ${APP_USER}

EXPOSE 8000

# Compose defines the authoritative healthcheck; this one keeps `docker run`
# and `docker ps` honest for anyone poking at the image directly.
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=5 \
    CMD curl -fsS "http://127.0.0.1:${API_PORT}/api/health" || exit 1

CMD ["sh", "-c", "exec uvicorn spectra_api.main:app --host \"${API_HOST}\" --port \"${API_PORT}\" --proxy-headers --forwarded-allow-ips '*'"]

# =========================== stage: worker =================================
# Identical image content, different entrypoint.  `docker/worker.Dockerfile`
# produces the same result by layering on an already-built API image; this
# target exists so the dev compose can build the worker without depending on
# the API image having been built first.
FROM runtime AS worker

ENV SPECTRA_ROLE=worker

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=5 \
    CMD pgrep -f spectra_worker >/dev/null || exit 1

CMD ["python", "-m", "spectra_worker"]
