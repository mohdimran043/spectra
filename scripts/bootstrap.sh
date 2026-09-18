#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Developer bootstrap: virtualenv, dependencies, .env, data dirs, local DB.
# Docker is NOT required - this sets up the embedded (SQLite + filesystem)
# profile so the stack runs on a laptop with no infrastructure at all.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

usage() {
    cat <<'USAGE_EOF'
bootstrap.sh - prepare a local development environment

SYNOPSIS
    ./scripts/bootstrap.sh [--ml] [--backends] [--recreate]

WHAT IT DOES
    1. Creates .venv with the configured Python (PYTHON=python3.12 to override).
    2. Installs the monorepo in editable mode with the [dev] extra.
    3. Copies .env.example to .env if you do not have one yet.
    4. Creates data/{runtime,uploads,processed} and models/.
    5. Initialises the local database through the SPECTRA CLI when available.

    No Docker, no PostgreSQL, no GPU required.  Use `make up` afterwards if you
    want the full containerised stack.

OPTIONS
    --ml         also install the heavy [ml] extra (torch, whisper, opencv)
    --backends   also install [backends] (qdrant, opensearch, neo4j, redis, s3)
    --recreate   delete and rebuild .venv
    -h, --help   this text
USAGE_EOF
}

for arg in "$@"; do
    case "${arg}" in -h|--help) usage; exit 0 ;; esac
done

WITH_ML=0
WITH_BACKENDS=0
RECREATE=0
for arg in "$@"; do
    case "${arg}" in
        --ml)       WITH_ML=1 ;;
        --backends) WITH_BACKENDS=1 ;;
        --recreate) RECREATE=1 ;;
        *) printf 'unknown argument: %s (try --help)\n' "${arg}" >&2; exit 1 ;;
    esac
done

PYTHON="${PYTHON:-python3}"
VENV="${REPO_ROOT}/.venv"

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
note() { printf '    %s\n' "$*"; }

step "Python environment"
command -v "${PYTHON}" >/dev/null || { printf 'ERROR: %s not found\n' "${PYTHON}" >&2; exit 1; }
note "$("${PYTHON}" --version)"

if [[ ${RECREATE} -eq 1 && -d "${VENV}" ]]; then
    note "removing the existing virtualenv"
    rm -rf -- "${VENV}"
fi

if [[ ! -d "${VENV}" ]]; then
    "${PYTHON}" -m venv "${VENV}"
    note "created ${VENV}"
else
    note "reusing ${VENV}"
fi

PIP="${VENV}/bin/pip"
PY="${VENV}/bin/python"

step "Dependencies"
"${PIP}" install --upgrade pip setuptools wheel >/dev/null
EXTRAS="dev"
[[ ${WITH_BACKENDS} -eq 1 ]] && EXTRAS="${EXTRAS},backends"
[[ ${WITH_ML} -eq 1 ]]       && EXTRAS="${EXTRAS},ml"
note "installing spectra[${EXTRAS}] in editable mode"
"${PIP}" install -e "${REPO_ROOT}[${EXTRAS}]"

step "Configuration"
if [[ -f "${REPO_ROOT}/.env" ]]; then
    note ".env already exists; leaving it alone"
else
    cp "${REPO_ROOT}/.env.example" "${REPO_ROOT}/.env"
    note "created .env from .env.example (embedded backends, no infrastructure needed)"
fi

step "Directories"
mkdir -p "${REPO_ROOT}"/data/{runtime,uploads,processed,demo} "${REPO_ROOT}/models"
note "data/ and models/ ready"

step "Database"
if [[ -x "${VENV}/bin/spectra" ]] && "${VENV}/bin/spectra" --help >/dev/null 2>&1; then
    if "${VENV}/bin/spectra" init-db 2>/dev/null; then
        note "local database initialised via the spectra CLI"
    else
        note "the spectra CLI has no init-db yet; the API creates the schema on first start"
    fi
else
    note "the spectra CLI is not available yet; the API creates the schema on first start"
fi

step "Ready"
note "activate:  source .venv/bin/activate"
note "run API:   uvicorn spectra_api.main:app --reload --port 8000"
note "run worker: python -m spectra_worker"
note "tests:     ./scripts/test.sh        lint: ./scripts/lint.sh"
note "full stack: make up"
"${PY}" - <<'PY' 2>/dev/null || true
try:
    from spectra_config.settings import get_settings
    s = get_settings()
    print(f"    settings ok: relational={s.relational_backend.value} vector={s.vector_backend.value} "
          f"profile={s.model_profile.value}")
except Exception as exc:  # noqa: BLE001 - diagnostics only
    print(f"    settings not importable yet: {exc}")
PY
