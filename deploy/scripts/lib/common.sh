#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# SPECTRA operator scripts - shared library.  Sourced, never executed.
#
# Resolves paths the same way whether the scripts run from a sealed bundle
# (scripts/ next to docker-compose.yml) or from the repository (deploy/scripts/
# next to docker-compose.lan.yml), so there is exactly one implementation of
# every operator primitive.
# ---------------------------------------------------------------------------

set -euo pipefail

# --- paths -----------------------------------------------------------------
SPECTRA_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="$(cd "${SPECTRA_LIB_DIR}/.." && pwd)"
DEPLOY_DIR="$(cd "${SCRIPTS_DIR}/.." && pwd)"

APP_SLUG="spectra"
ENV_FILE="${SPECTRA_ENV_FILE:-${DEPLOY_DIR}/.env}"
ENV_EXAMPLE_FILE="${DEPLOY_DIR}/.env.example"
IMAGES_DIR="${DEPLOY_DIR}/images"
CONFIG_TEMPLATE_DIR="${DEPLOY_DIR}/config"
UI_SOURCE_DIR="${DEPLOY_DIR}/ui"

# A bundle never contains docker-compose.lan.yml - package-release.sh renames it
# to docker-compose.yml - so its presence is what distinguishes the repository
# checkout (where docker-compose.yml is the *developer* stack) from a bundle.
# SPECTRA_COMPOSE_FILE overrides both, which is how `make db-migrate` and
# `make verify` point the operator scripts at the dev stack.
if [[ -f "${DEPLOY_DIR}/docker-compose.lan.yml" ]]; then
    COMPOSE_FILE="${SPECTRA_COMPOSE_FILE:-${DEPLOY_DIR}/docker-compose.lan.yml}"
else
    COMPOSE_FILE="${SPECTRA_COMPOSE_FILE:-${DEPLOY_DIR}/docker-compose.yml}"
fi
GPU_COMPOSE_FILE="${DEPLOY_DIR}/docker-compose.lan.gpu.yml"

if [[ -d "${DEPLOY_DIR}/db" ]]; then
    DB_DIR="${DEPLOY_DIR}/db"
else
    DB_DIR="$(cd "${DEPLOY_DIR}/.." && pwd)/db"
fi

# --- service inventory -----------------------------------------------------
# Kept in sync with docker-compose.lan.yml by hand; the audit in
# docs/deployment.md is what catches drift.
SPECTRA_APP_SERVICES=(api worker frontend mock-enterprise)
SPECTRA_INFRA_SERVICES=(postgres qdrant opensearch neo4j redis minio)
SPECTRA_DB_SERVICE="postgres"

# --- output ----------------------------------------------------------------
if [[ -t 1 ]]; then
    C_RESET=$'\033[0m'; C_RED=$'\033[31m'; C_GREEN=$'\033[32m'
    C_YELLOW=$'\033[33m'; C_BLUE=$'\033[34m'; C_BOLD=$'\033[1m'
else
    C_RESET=""; C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""; C_BOLD=""
fi

log()     { printf '%s\n' "$*"; }
info()    { printf '%s==>%s %s\n' "${C_BLUE}" "${C_RESET}" "$*"; }
ok()      { printf '%s  ok%s %s\n' "${C_GREEN}" "${C_RESET}" "$*"; }
warn()    { printf '%sWARN%s %s\n' "${C_YELLOW}" "${C_RESET}" "$*" >&2; }
err()     { printf '%sERROR%s %s\n' "${C_RED}" "${C_RESET}" "$*" >&2; }
die()     { err "$*"; exit 1; }
section() { printf '\n%s%s%s\n' "${C_BOLD}" "$*" "${C_RESET}"; }

now_utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# --- generic guards --------------------------------------------------------
require_cmd() {
    local cmd
    for cmd in "$@"; do
        command -v "${cmd}" >/dev/null 2>&1 || die "required command not found: ${cmd}"
    done
}

require_docker() {
    require_cmd docker
    docker compose version >/dev/null 2>&1 \
        || die "'docker compose' (v2) is required; 'docker-compose' v1 is not supported"
    docker info >/dev/null 2>&1 \
        || die "cannot talk to the Docker daemon. Is it running, and is this user in the docker group?"
}

# --- environment -----------------------------------------------------------
# Parses .env without sourcing it, so a stray backtick in a password cannot
# execute anything.  Tolerates CRLF line endings.
load_env() {
    [[ -f "${ENV_FILE}" ]] || die ".env not found at ${ENV_FILE}
Create it first:  cp .env.example .env   then replace every CHANGE_ME value."

    local line key value
    while IFS= read -r line || [[ -n "${line}" ]]; do
        line="${line%$'\r'}"
        [[ "${line}" =~ ^[[:space:]]*# ]] && continue
        [[ "${line}" =~ ^[[:space:]]*$ ]] && continue
        [[ "${line}" == *"="* ]] || continue
        key="${line%%=*}"
        value="${line#*=}"
        key="${key//[[:space:]]/}"
        [[ "${key}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
        # Strip one layer of matching surrounding quotes.
        if [[ "${value}" == \"*\" && ${#value} -ge 2 ]]; then
            value="${value:1:${#value}-2}"
        elif [[ "${value}" == \'*\' && ${#value} -ge 2 ]]; then
            value="${value:1:${#value}-2}"
        fi
        export "${key}=${value}"
    done < "${ENV_FILE}"

    APP_VERSION="${APP_VERSION:-}"
    [[ -n "${APP_VERSION}" ]] || die "APP_VERSION is not set in ${ENV_FILE}"
    APP_ROOT="${APP_ROOT:-}"
    [[ -n "${APP_ROOT}" ]] || die "APP_ROOT is not set in ${ENV_FILE}"
    [[ "${APP_ROOT}" == /* ]] || die "APP_ROOT must be an absolute path (got '${APP_ROOT}')"
    COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-${APP_SLUG}}"
    export APP_VERSION APP_ROOT COMPOSE_PROJECT_NAME
}

require_no_change_me() {
    local hits
    hits="$(grep -n 'CHANGE_ME' "${ENV_FILE}" | grep -v '^[0-9]*:[[:space:]]*#' || true)"
    if [[ -n "${hits}" ]]; then
        err "${ENV_FILE} still contains CHANGE_ME placeholders:"
        printf '%s\n' "${hits}" >&2
        die "replace every one of them before deploying"
    fi
    ok "no CHANGE_ME placeholders in .env"
}

# The stronger check: nothing may reach a container with a placeholder value.
require_no_change_me_in_config() {
    local rendered
    rendered="$(compose config 2>/dev/null || true)"
    if printf '%s' "${rendered}" | grep -q 'CHANGE_ME'; then
        err "the rendered compose configuration still contains CHANGE_ME:"
        printf '%s' "${rendered}" | grep -n 'CHANGE_ME' | head -n 20 >&2
        die "a required value is missing from ${ENV_FILE}"
    fi
    ok "rendered compose configuration is free of placeholders"
}

version_matches_bundle() {
    local bundle_version_file="${DEPLOY_DIR}/VERSION"
    [[ -f "${bundle_version_file}" ]] || return 0
    local bundle_version
    bundle_version="$(tr -d '[:space:]' < "${bundle_version_file}")"
    if [[ "${bundle_version}" != "${APP_VERSION}" ]]; then
        warn "APP_VERSION in .env is ${APP_VERSION} but this bundle is ${bundle_version}."
        warn "Set APP_VERSION=${bundle_version} unless you are deliberately pinning older images."
    fi
}

# --- compose ---------------------------------------------------------------
compose_files() {
    local files=(-f "${COMPOSE_FILE}")
    if [[ "${GPU_ENABLED:-0}" == "1" || "${GPU_ENABLED:-0}" == "true" ]]; then
        [[ -f "${GPU_COMPOSE_FILE}" ]] \
            || die "GPU_ENABLED=1 but ${GPU_COMPOSE_FILE} is missing from this bundle"
        files+=(-f "${GPU_COMPOSE_FILE}")
    fi
    printf '%s\n' "${files[@]}"
}

compose() {
    local -a files
    mapfile -t files < <(compose_files)
    docker compose \
        --project-name "${COMPOSE_PROJECT_NAME}" \
        --env-file "${ENV_FILE}" \
        "${files[@]}" "$@"
}

# The pattern's classic foot-gun: a stack already running under a different
# compose project name.  Renaming mid-life orphans every container and volume.
require_no_project_mismatch() {
    local existing
    existing="$(docker ps -a \
        --filter "label=com.docker.compose.project" \
        --filter "name=${CONTAINER_PREFIX:-spectra}-" \
        --format '{{.Label "com.docker.compose.project"}}' | sort -u | head -n 5)"
    [[ -z "${existing}" ]] && return 0
    local name
    while IFS= read -r name; do
        [[ -z "${name}" ]] && continue
        if [[ "${name}" != "${COMPOSE_PROJECT_NAME}" ]]; then
            err "a SPECTRA stack is already running under compose project '${name}'"
            err "but .env says COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME}."
            err "Fix it one of two ways:"
            err "  1. set COMPOSE_PROJECT_NAME=${name} in ${ENV_FILE}   (keeps the running stack), or"
            err "  2. run ./scripts/bootstrap-patch-support.sh          (adopts the running stack)"
            die "refusing to deploy into a mismatched project"
        fi
    done <<< "${existing}"
    ok "compose project name matches the running stack (${COMPOSE_PROJECT_NAME})"
}

# --- $APP_ROOT tree --------------------------------------------------------
ensure_app_root_tree() {
    local dirs=(
        "${APP_ROOT}"
        "${APP_ROOT}/config"
        "${APP_ROOT}/certs"
        "${APP_ROOT}/backups"
        "${APP_ROOT}/releases"
        "${APP_ROOT}/releases/ui"
        "${APP_ROOT}/releases/patches"
        "${APP_ROOT}/releases/patches/applied"
        "${APP_ROOT}/models"
        "${APP_ROOT}/data"
        "${APP_ROOT}/data/app"
        "${APP_ROOT}/data/postgres"
        "${APP_ROOT}/data/qdrant"
        "${APP_ROOT}/data/opensearch"
        "${APP_ROOT}/data/neo4j"
        "${APP_ROOT}/data/neo4j/data"
        "${APP_ROOT}/data/neo4j/logs"
        "${APP_ROOT}/data/redis"
        "${APP_ROOT}/data/minio"
    )
    local dir
    for dir in "${dirs[@]}"; do
        if [[ ! -d "${dir}" ]]; then
            mkdir -p "${dir}" 2>/dev/null \
                || die "cannot create ${dir}. Run as a user that owns ${APP_ROOT}, or pre-create it."
        fi
    done
    ok "state tree present under ${APP_ROOT}"
}

# Bind mounts need host-side ownership matching the uid each image runs as.
# Failures are warnings, not errors: an unprivileged operator may have had the
# directories pre-created correctly by their administrator.
chown_data_dirs() {
    local pairs=(
        "${APP_ROOT}/data/app:${APP_UID:-10001}:${APP_GID:-10001}"
        "${APP_ROOT}/models:${APP_UID:-10001}:${APP_GID:-10001}"
        "${APP_ROOT}/data/qdrant:${QDRANT_UID:-1000}:${QDRANT_GID:-1000}"
        "${APP_ROOT}/data/opensearch:${OPENSEARCH_UID:-1000}:${OPENSEARCH_GID:-1000}"
        "${APP_ROOT}/data/neo4j/data:${NEO4J_UID:-7474}:${NEO4J_GID:-7474}"
        "${APP_ROOT}/data/neo4j/logs:${NEO4J_UID:-7474}:${NEO4J_GID:-7474}"
        "${APP_ROOT}/data/redis:${REDIS_UID:-999}:${REDIS_GID:-999}"
        "${APP_ROOT}/data/minio:${MINIO_UID:-1000}:${MINIO_GID:-1000}"
    )
    local entry path owner
    for entry in "${pairs[@]}"; do
        path="${entry%%:*}"
        owner="${entry#*:}"
        chown -R "${owner}" "${path}" 2>/dev/null \
            || warn "could not chown ${path} to ${owner} (needs root); ensure it is writable by that uid"
    done
    # postgres chowns its own PGDATA from the image entrypoint.
}

# --- health ----------------------------------------------------------------
service_health() {
    local service="$1" cid
    cid="$(compose ps -q "${service}" 2>/dev/null | head -n 1)"
    [[ -n "${cid}" ]] || { printf 'absent'; return; }
    docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
        "${cid}" 2>/dev/null || printf 'unknown'
}

wait_for_healthy() {
    local service="$1" timeout="${2:-300}" waited=0 status
    info "waiting for ${service} to become healthy (timeout ${timeout}s)"
    while (( waited < timeout )); do
        status="$(service_health "${service}")"
        case "${status}" in
            healthy|running) ok "${service} is ${status}"; return 0 ;;
            exited|dead)     die "${service} exited while starting. Inspect: ./scripts/show-state.sh --logs ${service}" ;;
        esac
        sleep 5
        waited=$(( waited + 5 ))
    done
    die "${service} did not become healthy within ${timeout}s (last status: ${status:-unknown})"
}

# --- deployed state --------------------------------------------------------
state_file()        { printf '%s/.deployed-state.json' "${APP_ROOT}"; }
history_file()      { printf '%s/.deployed-history.jsonl' "${APP_ROOT}"; }
version_file()      { printf '%s/.deployed_version' "${APP_ROOT}"; }

deployed_version() {
    local f; f="$(version_file)"
    [[ -f "${f}" ]] && tr -d '[:space:]' < "${f}" || printf ''
}

json_escape() {
    printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/\t/\\t/g'
}

is_app_service() {
    local candidate
    for candidate in "${SPECTRA_APP_SERVICES[@]}"; do
        [[ "${candidate}" == "$1" ]] && return 0
    done
    return 1
}

# What image is this service actually on?  A running container is authoritative;
# otherwise reproduce the rule docker-compose.lan.yml applies, which differs for
# SPECTRA-built services (spectra-<svc>:${APP_VERSION}) and third-party ones
# (${<SVC>_IMAGE}).
resolved_service_image() {
    local service="$1" upper var cid image
    upper="$(printf '%s' "${service}" | tr '[:lower:]-' '[:upper:]_')"

    cid="$(compose ps -q "${service}" 2>/dev/null | head -n 1)"
    if [[ -n "${cid}" ]]; then
        image="$(docker inspect --format '{{.Config.Image}}' "${cid}" 2>/dev/null || true)"
        [[ -n "${image}" ]] && { printf '%s' "${image}"; return; }
    fi

    var="SERVICE_${upper}_IMAGE"
    image="${!var:-}"
    [[ -n "${image}" ]] && { printf '%s' "${image}"; return; }

    if is_app_service "${service}"; then
        printf '%s-%s:%s' "${APP_SLUG}" "${service}" "${APP_VERSION}"
        return
    fi

    var="${upper}_IMAGE"
    image="${!var:-}"
    printf '%s' "${image:-unknown (not running, ${var} unset)}"
}

# record_deployment <type> <version> [note]
# Appends one line to the history journal and regenerates .deployed-state.json.
# A journal plus a regenerated view keeps the scripts JSON-parser-free, which
# matters on an air-gapped host with no jq.
record_deployment() {
    local deployment_type="$1" version="$2" note="${3:-}"
    local ts; ts="$(now_utc)"
    local services=("${SPECTRA_APP_SERVICES[@]}" "${SPECTRA_INFRA_SERVICES[@]}")
    local svc image entries="" first=1

    for svc in "${services[@]}"; do
        image="$(resolved_service_image "${svc}")"
        [[ ${first} -eq 1 ]] && first=0 || entries+=",\n"
        entries+="    \"$(json_escape "${svc}")\": {\"image\": \"$(json_escape "${image}")\"}"
    done

    printf '{"at": "%s", "type": "%s", "version": "%s", "note": "%s"}\n' \
        "${ts}" "$(json_escape "${deployment_type}")" "$(json_escape "${version}")" "$(json_escape "${note}")" \
        >> "$(history_file)"

    {
        printf '{\n'
        printf '  "app": "%s",\n' "${APP_SLUG}"
        printf '  "app_version": "%s",\n' "$(json_escape "${version}")"
        printf '  "deployment_type": "%s",\n' "$(json_escape "${deployment_type}")"
        printf '  "deployed_at": "%s",\n' "${ts}"
        printf '  "compose_project": "%s",\n' "$(json_escape "${COMPOSE_PROJECT_NAME}")"
        printf '  "app_root": "%s",\n' "$(json_escape "${APP_ROOT}")"
        printf '  "gpu_enabled": %s,\n' "$([[ "${GPU_ENABLED:-0}" == "1" ]] && printf 'true' || printf 'false')"
        printf '  "note": "%s",\n' "$(json_escape "${note}")"
        printf '  "services": {\n'
        printf '%b\n' "${entries}"
        printf '  },\n'
        printf '  "history": [\n'
        tail -n 50 "$(history_file)" | sed -e 's/^/    /' -e '$ ! s/$/,/'
        printf '  ]\n'
        printf '}\n'
    } > "$(state_file)"

    printf '%s\n' "${version}" > "$(version_file)"
    ok "recorded ${deployment_type} of ${version} in $(state_file)"
}

# --- help ------------------------------------------------------------------
# Every script calls this first: `handle_help "$@"`.
handle_help() {
    local arg
    for arg in "$@"; do
        case "${arg}" in
            -h|--help) usage; exit 0 ;;
        esac
    done
}
