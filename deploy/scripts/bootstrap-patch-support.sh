#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# One-time preparation of a host that was installed before patch support, or
# whose running stack does not match the compose project name in .env.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

usage() {
    cat <<'USAGE_EOF'
bootstrap-patch-support.sh - make an existing host patchable

SYNOPSIS
    ./scripts/bootstrap-patch-support.sh [--adopt-project NAME] [--dry-run]

WHEN TO RUN IT
    Once, on a host that was installed before the patch workflow existed, or
    when deploy.sh refuses to start with a COMPOSE_PROJECT_NAME mismatch.
    It is safe to rerun; nothing here restarts containers.

WHAT IT DOES
    1. Creates the parts of the $APP_ROOT tree patches rely on:
         releases/ui  releases/patches  releases/patches/applied  backups
    2. Detects the compose project the running containers actually belong to and
       writes it into .env as COMPOSE_PROJECT_NAME, so `docker compose` addresses
       the live stack instead of starting a second one.
    3. Reconstructs $APP_ROOT/.deployed_version and .deployed-state.json from
       what is running, so deploy-patch.sh can check the base version.

OPTIONS
    --adopt-project NAME  use this project name instead of the detected one
    --dry-run             report what would change, change nothing
    -h, --help            this text
USAGE_EOF
}

handle_help "$@"
require_docker
load_env

ADOPT_PROJECT=""
DRY_RUN=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --adopt-project) ADOPT_PROJECT="${2:?--adopt-project needs a value}"; shift 2 ;;
        --dry-run)       DRY_RUN=1; shift ;;
        *) die "unknown argument: $1 (try --help)" ;;
    esac
done

# --- 1. tree --------------------------------------------------------------
section "1/3  State tree"
if [[ ${DRY_RUN} -eq 1 ]]; then
    info "would ensure the $APP_ROOT tree under ${APP_ROOT}"
else
    ensure_app_root_tree
fi

# --- 2. compose project ---------------------------------------------------
section "2/3  Compose project name"
detected="${ADOPT_PROJECT}"
if [[ -z "${detected}" ]]; then
    detected="$(docker ps -a \
        --filter "name=${CONTAINER_PREFIX:-spectra}-" \
        --format '{{.Label "com.docker.compose.project"}}' | sort | uniq -c | sort -rn | head -n 1 | awk '{print $2}')"
fi

if [[ -z "${detected}" ]]; then
    info "no running SPECTRA containers found; keeping COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME}"
elif [[ "${detected}" == "${COMPOSE_PROJECT_NAME}" ]]; then
    ok "already correct: COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME}"
else
    warn "the running stack belongs to compose project '${detected}'"
    if [[ ${DRY_RUN} -eq 1 ]]; then
        info "would set COMPOSE_PROJECT_NAME=${detected} in ${ENV_FILE}"
    else
        backup="${ENV_FILE}.$(date -u +%Y%m%d%H%M%S).pre-bootstrap.bak"
        cp "${ENV_FILE}" "${backup}"
        if grep -qE '^[[:space:]]*COMPOSE_PROJECT_NAME=' "${ENV_FILE}"; then
            sed -i -E "s|^[[:space:]]*COMPOSE_PROJECT_NAME=.*$|COMPOSE_PROJECT_NAME=${detected}|" "${ENV_FILE}"
        else
            printf 'COMPOSE_PROJECT_NAME=%s\n' "${detected}" >> "${ENV_FILE}"
        fi
        COMPOSE_PROJECT_NAME="${detected}"
        export COMPOSE_PROJECT_NAME
        ok "adopted project '${detected}' (.env backed up to ${backup})"
    fi
fi

# --- 3. deployed state ----------------------------------------------------
section "3/3  Deployed state"
existing_version="$(deployed_version)"
if [[ -n "${existing_version}" ]]; then
    ok "$(version_file) already records ${existing_version}"
else
    # Infer the version from the tag of the running api image.
    api_image="$(resolved_service_image api)"
    inferred="${api_image##*:}"
    [[ -n "${inferred}" && "${inferred}" != "${api_image}" ]] || inferred="${APP_VERSION}"
    if [[ ${DRY_RUN} -eq 1 ]]; then
        info "would record deployed version ${inferred} (from ${api_image})"
    else
        record_deployment "bootstrap" "${inferred}" "state reconstructed from running containers"
        ok "recorded ${inferred}"
    fi
fi

section "Ready for patches"
log "  Copy a patch archive into either inbox and run deploy-patch.sh:"
log "    ${DEPLOY_DIR}/releases/patches/"
log "    ${APP_ROOT}/releases/patches/"
log "    ./scripts/deploy-patch.sh"
