#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# SPECTRA full deploy - first install and version upgrade.
#
# Run from the extracted bundle directory (the one holding docker-compose.yml):
#     cp .env.example .env    # first install only; then replace every CHANGE_ME
#     ./scripts/deploy.sh
#     ./scripts/verify-deployment.sh
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

usage() {
    cat <<'USAGE_EOF'
deploy.sh - install or upgrade the SPECTRA stack on this host

SYNOPSIS
    ./scripts/deploy.sh [OPTIONS]

SEQUENCE
    1.  Preflight: Docker reachable, .env present, zero CHANGE_ME values, no
        compose-project-name mismatch with an already-running stack.
    2.  Ensure the $APP_ROOT tree (config/ certs/ data/<store>/ releases/ui
        releases/patches/{,applied} backups/) and fix bind-mount ownership.
    3.  Install config templates - FIRST RUN ONLY, never overwriting operator edits.
    4.  Generate a self-signed TLS certificate if none exists.
    5.  docker load every images/*.tar.gz in the bundle.
    6.  Start postgres first, wait for health, back up when this is an upgrade,
        then apply baseline + migrations.
    7.  Stage the UI build into $APP_ROOT/releases/ui/<version> and flip `current`.
    8.  docker compose up -d for the whole stack and wait for the API.
    9.  Record $APP_ROOT/.deployed_version and .deployed-state.json.

OPTIONS
    --skip-images        do not docker load (images already on this host)
    --skip-migrations    do not touch the database (you will run them yourself)
    --skip-backup        do not back up before an upgrade  [NOT RECOMMENDED]
    --keep-image-overrides
                         keep any SERVICE_*_IMAGE patch pins in .env instead of
                         clearing them; use only to deliberately hold a patch
    --no-wait            return as soon as `up -d` returns, without health waits
    -h, --help           this text

UPGRADE
    Copy the previous .env into the new bundle first - it carries every
    site-specific value:
        cp /path/to/previous-bundle/.env .env
        ./scripts/deploy.sh

DATABASE
    Migrations are forward-only.  rollback.sh restores images and UI; it never
    reverts schema.  The pre-upgrade backup in $APP_ROOT/backups is the only way
    back from a destructive migration.
USAGE_EOF
}

handle_help "$@"

SKIP_IMAGES=0
SKIP_MIGRATIONS=0
SKIP_BACKUP=0
KEEP_OVERRIDES=0
NO_WAIT=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-images)          SKIP_IMAGES=1; shift ;;
        --skip-migrations)      SKIP_MIGRATIONS=1; shift ;;
        --skip-backup)          SKIP_BACKUP=1; shift ;;
        --keep-image-overrides) KEEP_OVERRIDES=1; shift ;;
        --no-wait)              NO_WAIT=1; shift ;;
        *) die "unknown argument: $1 (try --help)" ;;
    esac
done

# ===========================================================================
# 1. Preflight
# ===========================================================================
section "1/9  Preflight"
require_docker
ok "docker daemon reachable"
load_env
ok "configuration loaded from ${ENV_FILE}"
version_matches_bundle
require_no_change_me
require_no_project_mismatch

PREVIOUS_VERSION="$(deployed_version)"
if [[ -z "${PREVIOUS_VERSION}" ]]; then
    DEPLOY_KIND="first-install"
elif [[ "${PREVIOUS_VERSION}" == "${APP_VERSION}" ]]; then
    DEPLOY_KIND="redeploy"
else
    DEPLOY_KIND="upgrade"
fi
info "deployment type: ${DEPLOY_KIND} (previous: ${PREVIOUS_VERSION:-none}, target: ${APP_VERSION})"

# ===========================================================================
# 2. State tree
# ===========================================================================
section "2/9  State tree"
ensure_app_root_tree
chown_data_dirs

# ===========================================================================
# 3. Config templates - first run only
# ===========================================================================
section "3/9  Config"
if [[ -d "${CONFIG_TEMPLATE_DIR}" ]]; then
    installed=0
    while IFS= read -r template; do
        [[ -z "${template}" ]] && continue
        name="$(basename "${template}")"
        target="${APP_ROOT}/config/${name}"
        if [[ -e "${target}" ]]; then
            ok "keeping existing ${target}"
        else
            cp "${template}" "${target}"
            installed=$(( installed + 1 ))
            ok "installed ${target}"
        fi
    done < <(find "${CONFIG_TEMPLATE_DIR}" -maxdepth 1 -type f | sort)
    info "${installed} config file(s) installed; existing files were left untouched"
else
    info "no config templates in this bundle"
fi

# ===========================================================================
# 4. TLS
# ===========================================================================
section "4/9  TLS"
if [[ -f "${APP_ROOT}/certs/server.crt" && -f "${APP_ROOT}/certs/server.key" ]]; then
    ok "certificate already present at ${APP_ROOT}/certs"
else
    "${SCRIPT_DIR}/generate-ssl.sh"
fi

# ===========================================================================
# 5. Images
# ===========================================================================
section "5/9  Images"
if [[ ${SKIP_IMAGES} -eq 1 ]]; then
    info "--skip-images given; nothing loaded"
elif [[ -d "${IMAGES_DIR}" ]]; then
    "${SCRIPT_DIR}/import-images.sh" "${IMAGES_DIR}"
else
    warn "no images/ directory in this bundle; assuming the images are already on this host"
fi

# A full release supersedes any per-service patch pin.  Leaving a stale
# SERVICE_*_IMAGE in .env is the quietest way to deploy a new version and keep
# running the old code for one service.
clear_patch_overrides() {
    local overrides
    overrides="$(grep -E '^[[:space:]]*SERVICE_[A-Z0-9_]+_IMAGE=.+' "${ENV_FILE}" || true)"
    [[ -z "${overrides}" ]] && { ok "no per-service image overrides in .env"; return; }

    if [[ ${KEEP_OVERRIDES} -eq 1 ]]; then
        warn "--keep-image-overrides: these pins stay in effect"
        printf '%s\n' "${overrides}" | sed 's/^/     /' >&2
        return
    fi

    local backup="${ENV_FILE}.$(date -u +%Y%m%d%H%M%S).bak"
    cp "${ENV_FILE}" "${backup}"
    sed -i -E 's/^([[:space:]]*SERVICE_[A-Z0-9_]+_IMAGE=.+)$/#superseded-by-release \1/' "${ENV_FILE}"
    warn "cleared patch image pins so this release applies everywhere (.env backed up to ${backup}):"
    printf '%s\n' "${overrides}" | sed 's/^/     /' >&2
    load_env
}
clear_patch_overrides
require_no_change_me_in_config

# ===========================================================================
# 6. Database
# ===========================================================================
section "6/9  Database"
info "starting ${SPECTRA_DB_SERVICE} ahead of the rest of the stack"
compose up -d "${SPECTRA_DB_SERVICE}"
wait_for_healthy "${SPECTRA_DB_SERVICE}" "${DB_WAIT_TIMEOUT:-180}"

if [[ "${DEPLOY_KIND}" == "upgrade" && ${SKIP_BACKUP} -eq 0 ]]; then
    info "upgrade detected (${PREVIOUS_VERSION} -> ${APP_VERSION}); backing up first"
    "${SCRIPT_DIR}/backup-data.sh" --label "pre-${APP_VERSION}"
elif [[ "${DEPLOY_KIND}" == "upgrade" ]]; then
    warn "--skip-backup on an upgrade: there will be no way back from a destructive migration"
else
    info "no backup needed for a ${DEPLOY_KIND}"
fi

if [[ ${SKIP_MIGRATIONS} -eq 1 ]]; then
    warn "--skip-migrations given; the schema may not match this release"
else
    "${SCRIPT_DIR}/run-migrations.sh"
fi

# ===========================================================================
# 7. UI release
# ===========================================================================
section "7/9  UI"
UI_BUNDLE_DIR="${UI_SOURCE_DIR}/${APP_VERSION}"
if [[ -d "${UI_BUNDLE_DIR}" ]]; then
    target="${APP_ROOT}/releases/ui/${APP_VERSION}"
    mkdir -p "${target}"
    cp -r "${UI_BUNDLE_DIR}/." "${target}/"
    ln -sfn "${target}" "${APP_ROOT}/releases/ui/current"
    ok "UI ${APP_VERSION} staged at ${target} (current -> ${APP_VERSION})"
else
    # SPECTRA serves its UI from the frontend container, so this directory is a
    # provenance record rather than a web root.  Its absence is not an error.
    info "no prebuilt UI in this bundle; the frontend image serves the UI"
fi

# ===========================================================================
# 8. Bring the stack up
# ===========================================================================
section "8/9  Starting the stack"
compose up -d --remove-orphans
ok "compose up completed"

if [[ ${NO_WAIT} -eq 1 ]]; then
    warn "--no-wait: skipping health waits"
else
    for service in "${SPECTRA_INFRA_SERVICES[@]}"; do
        wait_for_healthy "${service}" "${INFRA_WAIT_TIMEOUT:-300}"
    done
    wait_for_healthy api "${API_WAIT_TIMEOUT:-420}"
    for service in worker frontend mock-enterprise; do
        wait_for_healthy "${service}" "${APP_WAIT_TIMEOUT:-300}"
    done
fi

# ===========================================================================
# 9. Record state
# ===========================================================================
section "9/9  Recording state"
record_deployment "${DEPLOY_KIND}" "${APP_VERSION}" "from bundle $(basename "${DEPLOY_DIR}")"

section "SPECTRA ${APP_VERSION} deployed"
log "  analyst UI        http://${SPECTRA_PUBLIC_HOST:-localhost}:${FRONTEND_PUBLISHED_PORT:-3000}"
log "  enterprise app    http://${SPECTRA_PUBLIC_HOST:-localhost}:${MOCK_ENTERPRISE_PUBLISHED_PORT:-3001}"
log "  API               http://${SPECTRA_PUBLIC_HOST:-localhost}:${API_PUBLISHED_PORT:-8000}/api/health"
log ""
log "  next:  ./scripts/verify-deployment.sh"
log "         ./scripts/show-state.sh"
