#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Apply a SPECTRA patch bundle on top of a running stack at the same base
# version.  Runs against the LIVE deploy directory, not a fresh extract.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

usage() {
    cat <<'USAGE_EOF'
deploy-patch.sh - apply a patch bundle to the running stack

SYNOPSIS
    ./scripts/deploy-patch.sh [PATCH.tar.gz] [--force] [--skip-verify]

FINDING THE PATCH
    With no argument the newest *.tar.gz is taken from, in order:
        ./releases/patches/            (next to docker-compose.yml)
        $APP_ROOT/releases/patches/
    Copy the archive into either directory and rerun with no arguments.

SEQUENCE
    1. Verify CHECKSUMS.sha256 inside the archive.
    2. Read patch-manifest.json; refuse if the base version does not match what
       is deployed, or if this patch id was already applied.
    3. docker load every image in the patch.
    4. Write the SERVICE_*_IMAGE pins from patch.env into the live .env, so the
       immutable docker-compose.yml starts the patched images.
    5. Run migrations when the patch carries db changes.
    6. Stage the UI and flip $APP_ROOT/releases/ui/current when it carries ui.
    7. Recreate ONLY the patched services (--no-deps --force-recreate).
    8. Append to the deployment journal and move the archive into
       releases/patches/applied/.

FIRST TIME ON AN OLDER HOST
    Run ./scripts/bootstrap-patch-support.sh once before the first patch.

OPTIONS
    --force         apply even on a base-version mismatch or a repeated patch id
    --skip-verify   do not run verify-deployment.sh afterwards
    -h, --help      this text
USAGE_EOF
}

handle_help "$@"
require_docker
require_cmd tar sha256sum
load_env

ARCHIVE=""
FORCE=0
SKIP_VERIFY=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --force)       FORCE=1; shift ;;
        --skip-verify) SKIP_VERIFY=1; shift ;;
        -*)            die "unknown option: $1 (try --help)" ;;
        *)             ARCHIVE="$1"; shift ;;
    esac
done

# --- 1. locate ------------------------------------------------------------
section "1/8  Locating the patch"
if [[ -z "${ARCHIVE}" ]]; then
    for inbox in "${DEPLOY_DIR}/releases/patches" "${APP_ROOT}/releases/patches"; do
        [[ -d "${inbox}" ]] || continue
        candidate="$(find "${inbox}" -maxdepth 1 -name '*.tar.gz' -printf '%T@ %p\n' 2>/dev/null \
                     | sort -rn | head -n 1 | cut -d' ' -f2-)"
        if [[ -n "${candidate}" ]]; then ARCHIVE="${candidate}"; break; fi
    done
fi

[[ -n "${ARCHIVE}" ]] || die "no patch archive found.
Copy the patch into one of these directories and rerun with no arguments:
  ${DEPLOY_DIR}/releases/patches/
  ${APP_ROOT}/releases/patches/"
[[ -f "${ARCHIVE}" ]] || die "patch archive not found: ${ARCHIVE}"
ok "using $(basename "${ARCHIVE}")"

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/spectra-patch-XXXXXX")"
cleanup() { rm -rf -- "${WORK_DIR}"; }
trap cleanup EXIT

info "extracting to ${WORK_DIR}"
tar -xzf "${ARCHIVE}" -C "${WORK_DIR}"
PATCH_DIR="$(find "${WORK_DIR}" -maxdepth 1 -mindepth 1 -type d | head -n 1)"
[[ -n "${PATCH_DIR}" ]] || die "the archive does not contain a patch directory"
[[ -f "${PATCH_DIR}/patch-manifest.json" ]] || die "patch-manifest.json missing - is this a full release rather than a patch?"

# --- 2. verify + manifest -------------------------------------------------
section "2/8  Verifying"
if [[ -f "${PATCH_DIR}/CHECKSUMS.sha256" ]]; then
    ( cd "${PATCH_DIR}" && sha256sum -c CHECKSUMS.sha256 --quiet ) \
        || die "checksum verification failed - the patch is corrupt or was tampered with"
    ok "checksums verified"
else
    warn "no CHECKSUMS.sha256 in this patch"
fi

manifest_get() {
    sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/p" \
        "${PATCH_DIR}/patch-manifest.json" | head -n 1
}
manifest_flag() {
    sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\(true\|false\).*/\1/p" \
        "${PATCH_DIR}/patch-manifest.json" | head -n 1
}

PATCH_ID="$(manifest_get patch_id)"
BASE_VERSION="$(manifest_get base_version)"
PATCH_SERVICES="$(manifest_get service_list)"
INCLUDES_DB="$(manifest_flag includes_db)"
INCLUDES_UI="$(manifest_flag includes_ui)"

[[ -n "${PATCH_ID}" ]]      || die "patch-manifest.json has no patch_id"
[[ -n "${BASE_VERSION}" ]]  || die "patch-manifest.json has no base_version"

info "patch id      ${PATCH_ID}"
info "base version  ${BASE_VERSION}"
info "services      ${PATCH_SERVICES:-none}"
info "includes db   ${INCLUDES_DB:-false}"
info "includes ui   ${INCLUDES_UI:-false}"

DEPLOYED="$(deployed_version)"
if [[ "${BASE_VERSION}" != "${DEPLOYED}" ]]; then
    if [[ ${FORCE} -eq 1 ]]; then
        warn "base version ${BASE_VERSION} != deployed ${DEPLOYED:-none}; --force given"
    else
        die "this patch targets ${BASE_VERSION} but ${DEPLOYED:-nothing} is deployed.
Deploy the matching full release first, or rerun with --force if you know better."
    fi
fi

if [[ -f "${APP_ROOT}/releases/patches/applied/$(basename "${ARCHIVE}")" && ${FORCE} -eq 0 ]]; then
    die "a patch archive with this name is already in releases/patches/applied.
Patch ids are never reused - rebuild with the next sequence number, or use --force."
fi

# --- 3. images ------------------------------------------------------------
section "3/8  Loading images"
if [[ -d "${PATCH_DIR}/images" ]]; then
    "${SCRIPT_DIR}/import-images.sh" "${PATCH_DIR}/images"
else
    info "this patch carries no images"
fi

# --- 4. image pins --------------------------------------------------------
section "4/8  Pinning patched images in .env"
set_env_var() {
    local key="$1" value="$2"
    if grep -qE "^[[:space:]]*(#superseded-by-release[[:space:]]+)?${key}=" "${ENV_FILE}"; then
        sed -i -E "s|^[[:space:]]*(#superseded-by-release[[:space:]]+)?${key}=.*$|${key}=${value}|" "${ENV_FILE}"
    else
        printf '%s=%s\n' "${key}" "${value}" >> "${ENV_FILE}"
    fi
    ok "${key}=${value}"
}

ENV_BACKUP="${ENV_FILE}.$(date -u +%Y%m%d%H%M%S).pre-${PATCH_ID}.bak"
cp "${ENV_FILE}" "${ENV_BACKUP}"
info ".env backed up to ${ENV_BACKUP}"

if [[ -f "${PATCH_DIR}/patch.env" ]]; then
    while IFS= read -r line; do
        line="${line%$'\r'}"
        [[ "${line}" =~ ^[[:space:]]*# ]] && continue
        [[ "${line}" == *"="* ]] || continue
        set_env_var "${line%%=*}" "${line#*=}"
    done < "${PATCH_DIR}/patch.env"
else
    warn "no patch.env in this patch; no image pins were changed"
fi

load_env
require_no_change_me_in_config

# --- 5. database ----------------------------------------------------------
section "5/8  Database"
if [[ "${INCLUDES_DB}" == "true" ]]; then
    if [[ -d "${PATCH_DIR}/db" ]]; then
        info "copying patch migrations into ${DB_DIR}/migrations"
        mkdir -p "${DB_DIR}/migrations"
        cp -n "${PATCH_DIR}/db/migrations/"*.sql "${DB_DIR}/migrations/" 2>/dev/null || true
    fi
    "${SCRIPT_DIR}/backup-data.sh" --label "pre-${PATCH_ID}"
    "${SCRIPT_DIR}/run-migrations.sh" --migrations-only
else
    info "this patch carries no database changes"
fi

# --- 6. ui ----------------------------------------------------------------
section "6/8  UI"
if [[ "${INCLUDES_UI}" == "true" && -d "${PATCH_DIR}/ui" ]]; then
    target="${APP_ROOT}/releases/ui/${PATCH_ID}"
    mkdir -p "${target}"
    cp -r "${PATCH_DIR}/ui/." "${target}/"
    ln -sfn "${target}" "${APP_ROOT}/releases/ui/current"
    ok "UI staged at ${target} (current -> ${PATCH_ID})"
else
    info "this patch carries no UI build"
fi

# --- 7. recreate ----------------------------------------------------------
section "7/8  Recreating patched services"
if [[ -n "${PATCH_SERVICES}" ]]; then
    # shellcheck disable=SC2086
    compose up -d --no-deps --force-recreate ${PATCH_SERVICES}
    for service in ${PATCH_SERVICES}; do
        wait_for_healthy "${service}" "${PATCH_WAIT_TIMEOUT:-300}"
    done
else
    info "no services listed in the manifest; nothing recreated"
fi

# --- 8. record ------------------------------------------------------------
section "8/8  Recording"
record_deployment "patch" "${BASE_VERSION}" "${PATCH_ID}"

mkdir -p "${APP_ROOT}/releases/patches/applied"
mv "${ARCHIVE}" "${APP_ROOT}/releases/patches/applied/"
ok "archive moved to ${APP_ROOT}/releases/patches/applied/$(basename "${ARCHIVE}")"

if [[ ${SKIP_VERIFY} -eq 0 ]]; then
    "${SCRIPT_DIR}/verify-deployment.sh" --quick
fi

section "Patch ${PATCH_ID} applied"
log "  base version stays ${BASE_VERSION}; patched services now run ${PATCH_ID} images."
log "  ./scripts/show-state.sh    to see the pins"
