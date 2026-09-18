#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# What is deployed on this host, right now.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

usage() {
    cat <<'USAGE_EOF'
show-state.sh - deployed version, per-service images, health and history

SYNOPSIS
    ./scripts/show-state.sh [--json] [--history] [--logs SERVICE [LINES]]

OUTPUT
    deployment  version, type and timestamp of the last deploy or patch
    services    container, image actually running, and health for each service
    storage     disk used by each bind mount under $APP_ROOT/data
    patches     patch archives waiting in releases/patches and already applied

OPTIONS
    --json              print $APP_ROOT/.deployed-state.json verbatim and exit
    --history           print the full deployment journal and exit
    --logs SERVICE [N]  tail N lines (default 200) of one service and exit
    -h, --help          this text
USAGE_EOF
}

handle_help "$@"
require_docker
load_env

case "${1:-}" in
    --json)
        [[ -f "$(state_file)" ]] || die "no state file at $(state_file); nothing has been deployed yet"
        cat "$(state_file)"
        exit 0
        ;;
    --history)
        [[ -f "$(history_file)" ]] || die "no deployment journal at $(history_file)"
        cat "$(history_file)"
        exit 0
        ;;
    --logs)
        service="${2:?--logs needs a service name}"
        lines="${3:-200}"
        compose logs --no-color --tail "${lines}" "${service}"
        exit 0
        ;;
    "") ;;
    *) die "unknown argument: $1 (try --help)" ;;
esac

section "Deployment"
printf '  %-18s %s\n' "app"             "${APP_SLUG}"
printf '  %-18s %s\n' "app_root"        "${APP_ROOT}"
printf '  %-18s %s\n' "compose project" "${COMPOSE_PROJECT_NAME}"
printf '  %-18s %s\n' "env APP_VERSION" "${APP_VERSION}"
printf '  %-18s %s\n' "deployed"        "$(deployed_version || echo '(never)')"
printf '  %-18s %s\n' "gpu"             "${GPU_ENABLED:-0}"

if [[ -f "$(state_file)" ]]; then
    last_type="$(grep -m1 '"deployment_type"' "$(state_file)" | sed -e 's/.*: *"//' -e 's/",*//')"
    last_at="$(grep -m1 '"deployed_at"'     "$(state_file)" | sed -e 's/.*: *"//' -e 's/",*//')"
    printf '  %-18s %s\n' "last action"  "${last_type:-unknown} at ${last_at:-unknown}"
else
    warn "no state file yet at $(state_file)"
fi

section "Services"
printf '  %-17s %-42s %s\n' "SERVICE" "IMAGE" "HEALTH"
for service in "${SPECTRA_APP_SERVICES[@]}" "${SPECTRA_INFRA_SERVICES[@]}"; do
    printf '  %-17s %-42s %s\n' \
        "${service}" \
        "$(resolved_service_image "${service}")" \
        "$(service_health "${service}")"
done

section "Image pins in .env"
pins="$(grep -E '^[[:space:]]*SERVICE_[A-Z0-9_]+_IMAGE=.+' "${ENV_FILE}" || true)"
if [[ -n "${pins}" ]]; then
    printf '%s\n' "${pins}" | sed 's/^/  /'
    warn "these override the ${APP_VERSION} images; they normally come from a patch"
else
    printf '  none (every service runs spectra-<svc>:%s)\n' "${APP_VERSION}"
fi

section "Storage"
if [[ -d "${APP_ROOT}/data" ]]; then
    du -sh "${APP_ROOT}"/data/* 2>/dev/null | sed 's/^/  /' || printf '  (unreadable)\n'
else
    printf '  no data directory yet\n'
fi
if [[ -d "${APP_ROOT}/backups" ]]; then
    printf '  backups: %s\n' "$(find "${APP_ROOT}/backups" -maxdepth 1 -mindepth 1 -type d | wc -l) directories, $(du -sh "${APP_ROOT}/backups" 2>/dev/null | cut -f1)"
fi

section "Patches"
pending_dirs=("${DEPLOY_DIR}/releases/patches" "${APP_ROOT}/releases/patches")
found=0
for dir in "${pending_dirs[@]}"; do
    [[ -d "${dir}" ]] || continue
    while IFS= read -r archive; do
        [[ -z "${archive}" ]] && continue
        printf '  pending  %s\n' "${archive}"
        found=1
    done < <(find "${dir}" -maxdepth 1 -name '*.tar.gz' | sort)
done
[[ ${found} -eq 0 ]] && printf '  no pending patch archives\n'

if [[ -d "${APP_ROOT}/releases/patches/applied" ]]; then
    applied_count="$(find "${APP_ROOT}/releases/patches/applied" -maxdepth 1 -name '*.tar.gz' | wc -l)"
    printf '  applied  %s archive(s) in %s\n' "${applied_count}" "${APP_ROOT}/releases/patches/applied"
    find "${APP_ROOT}/releases/patches/applied" -maxdepth 1 -name '*.tar.gz' | sort | tail -n 5 | sed 's/^/           /'
fi

section "Recent history"
if [[ -f "$(history_file)" ]]; then
    tail -n 10 "$(history_file)" | sed 's/^/  /'
else
    printf '  no history journal yet\n'
fi
