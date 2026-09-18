#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Roll the stack back to a previous release bundle - IMAGES AND UI ONLY.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

usage() {
    cat <<'USAGE_EOF'
rollback.sh - return to a previous release's images and UI

SYNOPSIS
    ./scripts/rollback.sh /path/to/spectra-<PREV_VERSION>/ [--yes] [--skip-images]

    The argument is the EXTRACTED previous bundle directory - the one holding
    that release's VERSION file and images/.

    ############################################################################
    ##                                                                        ##
    ##  THE DATABASE IS NEVER ROLLED BACK.                                     ##
    ##                                                                        ##
    ##  Migrations are forward-only.  This script reverts container images and ##
    ##  the staged UI; it does not and cannot undo schema changes.             ##
    ##                                                                        ##
    ##  If the upgrade you are undoing ran a destructive migration (dropped or ##
    ##  renamed a column, changed a type, rewrote data), the old code will hit ##
    ##  a schema it does not understand.  In that case you MUST restore the    ##
    ##  pre-upgrade dump BEFORE starting the old images:                       ##
    ##                                                                        ##
    ##    ls $APP_ROOT/backups/                                                ##
    ##    gunzip -c $APP_ROOT/backups/<dir>/<db>.sql.gz | \                    ##
    ##      docker compose exec -T postgres psql -U <user> -d <db>             ##
    ##                                                                        ##
    ##  Restoring a dump discards everything written since it was taken.       ##
    ##  Decide deliberately; this script will not decide for you.              ##
    ##                                                                        ##
    ############################################################################

WHAT IT DOES
    1. Reads VERSION from the previous bundle.
    2. Loads that bundle's images (unless --skip-images).
    3. Clears every SERVICE_*_IMAGE patch pin and sets APP_VERSION back.
    4. Recreates the application services on the old images.
    5. Points $APP_ROOT/releases/ui/current back at the old build if present.
    6. Records a "rollback" entry in the deployment journal.

OPTIONS
    --yes           do not ask for confirmation
    --skip-images   the old images are already on this host
    -h, --help      this text
USAGE_EOF
}

handle_help "$@"
require_docker
load_env

PREVIOUS_BUNDLE=""
ASSUME_YES=0
SKIP_IMAGES=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --yes|-y)      ASSUME_YES=1; shift ;;
        --skip-images) SKIP_IMAGES=1; shift ;;
        -*)            die "unknown option: $1 (try --help)" ;;
        *)             PREVIOUS_BUNDLE="$1"; shift ;;
    esac
done

[[ -n "${PREVIOUS_BUNDLE}" ]] || { usage; die "the previous bundle directory is required"; }
[[ -d "${PREVIOUS_BUNDLE}" ]] || die "not a directory: ${PREVIOUS_BUNDLE}"
[[ -f "${PREVIOUS_BUNDLE}/VERSION" ]] || die "${PREVIOUS_BUNDLE}/VERSION not found - is this an extracted SPECTRA bundle?"

TARGET_VERSION="$(tr -d '[:space:]' < "${PREVIOUS_BUNDLE}/VERSION")"
CURRENT_VERSION="$(deployed_version)"

section "Rollback ${CURRENT_VERSION:-unknown} -> ${TARGET_VERSION}"
printf '%s\n' "${C_YELLOW}"
cat <<'WARNING_EOF'
  ####################################################################
  #  DATABASE SCHEMA IS NOT ROLLED BACK.                             #
  #                                                                  #
  #  Images and UI revert.  The database stays exactly as the newer   #
  #  release left it.  If that release ran a destructive migration,   #
  #  restore the pre-upgrade dump from $APP_ROOT/backups FIRST, or    #
  #  the old code will fail against a schema it does not know.        #
  ####################################################################
WARNING_EOF
printf '%s\n' "${C_RESET}"

if [[ -d "${APP_ROOT}/backups" ]]; then
    info "available backups:"
    find "${APP_ROOT}/backups" -maxdepth 1 -mindepth 1 -type d | sort -r | head -n 5 | sed 's/^/     /'
fi

if [[ ${ASSUME_YES} -eq 0 ]]; then
    printf 'Type the target version (%s) to continue: ' "${TARGET_VERSION}"
    read -r answer
    [[ "${answer}" == "${TARGET_VERSION}" ]] || die "aborted"
fi

# --- images ---------------------------------------------------------------
section "Images"
if [[ ${SKIP_IMAGES} -eq 1 ]]; then
    info "--skip-images given"
elif [[ -d "${PREVIOUS_BUNDLE}/images" ]]; then
    "${SCRIPT_DIR}/import-images.sh" "${PREVIOUS_BUNDLE}/images"
else
    warn "no images/ in ${PREVIOUS_BUNDLE}; assuming the ${TARGET_VERSION} images are still on this host"
fi

# --- env ------------------------------------------------------------------
section "Configuration"
ENV_BACKUP="${ENV_FILE}.$(date -u +%Y%m%d%H%M%S).pre-rollback.bak"
cp "${ENV_FILE}" "${ENV_BACKUP}"
ok ".env backed up to ${ENV_BACKUP}"

# Patch pins belong to the version being abandoned.
sed -i -E 's/^([[:space:]]*SERVICE_[A-Z0-9_]+_IMAGE=.+)$/#rolled-back \1/' "${ENV_FILE}"
sed -i -E "s|^[[:space:]]*APP_VERSION=.*$|APP_VERSION=${TARGET_VERSION}|" "${ENV_FILE}"
ok "APP_VERSION=${TARGET_VERSION}, patch pins cleared"

load_env
require_no_change_me_in_config

# --- ui -------------------------------------------------------------------
section "UI"
if [[ -d "${APP_ROOT}/releases/ui/${TARGET_VERSION}" ]]; then
    ln -sfn "${APP_ROOT}/releases/ui/${TARGET_VERSION}" "${APP_ROOT}/releases/ui/current"
    ok "current -> ${TARGET_VERSION}"
elif [[ -d "${PREVIOUS_BUNDLE}/ui/${TARGET_VERSION}" ]]; then
    target="${APP_ROOT}/releases/ui/${TARGET_VERSION}"
    mkdir -p "${target}"
    cp -r "${PREVIOUS_BUNDLE}/ui/${TARGET_VERSION}/." "${target}/"
    ln -sfn "${target}" "${APP_ROOT}/releases/ui/current"
    ok "restored UI ${TARGET_VERSION} from the bundle"
else
    info "no staged UI for ${TARGET_VERSION}; the frontend image serves the UI"
fi

# --- restart --------------------------------------------------------------
section "Restarting services"
compose up -d --force-recreate "${SPECTRA_APP_SERVICES[@]}"
for service in "${SPECTRA_APP_SERVICES[@]}"; do
    wait_for_healthy "${service}" "${APP_WAIT_TIMEOUT:-300}"
done

record_deployment "rollback" "${TARGET_VERSION}" "rolled back from ${CURRENT_VERSION:-unknown}"

section "Rolled back to ${TARGET_VERSION}"
warn "The database was NOT rolled back. If the newer release changed the schema"
warn "destructively, restore a dump from ${APP_ROOT}/backups now."
log "  ./scripts/verify-deployment.sh"
