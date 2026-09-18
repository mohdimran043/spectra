#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Back up SPECTRA state into $APP_ROOT/backups before a risky operation.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

usage() {
    cat <<'USAGE_EOF'
backup-data.sh - snapshot the databases (and optionally object storage)

SYNOPSIS
    ./scripts/backup-data.sh [--label TEXT] [--with-objects] [--keep N]

WHAT IT DOES
    Writes a timestamped directory under $APP_ROOT/backups containing:
      * <control-db>.sql.gz     pg_dump of the SPECTRA control plane
      * <enterprise-db>.sql.gz  pg_dump of the enterprise demo database
      * manifest.txt            version, timestamp, per-file checksums
      * objects.tar.gz          only with --with-objects (MinIO data, can be large)

    deploy.sh calls this automatically when it detects a version upgrade.
    Run it yourself before anything you might want to undo.

    Vector, lexical and graph stores are NOT dumped: they are rebuildable from
    the control plane with a reindex.  Object storage is opt-in because it is
    usually the largest thing on the host.

RESTORE
    gunzip -c $APP_ROOT/backups/<dir>/<db>.sql.gz | \
      docker compose exec -T postgres psql -U <user> -d <db>

OPTIONS
    --label TEXT     suffix for the backup directory name
    --with-objects   also archive $APP_ROOT/data/minio
    --keep N         prune all but the newest N backups afterwards (default: keep all)
    -h, --help       this text
USAGE_EOF
}

handle_help "$@"
require_docker
load_env

LABEL=""
WITH_OBJECTS=0
KEEP=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --label)        LABEL="${2:?--label needs a value}"; shift 2 ;;
        --with-objects) WITH_OBJECTS=1; shift ;;
        --keep)         KEEP="${2:?--keep needs a value}"; shift 2 ;;
        *)              die "unknown argument: $1 (try --help)" ;;
    esac
done

CONTROL_DB="${POSTGRES_DB:-spectra}"
ENTERPRISE_DB_NAME="${ENTERPRISE_DB:-spectra_enterprise}"
PG_USER="${POSTGRES_USER:-spectra}"
PG_PASSWORD="${POSTGRES_PASSWORD:-}"
[[ -n "${PG_PASSWORD}" ]] || die "POSTGRES_PASSWORD is not set in ${ENV_FILE}"

STAMP="$(date -u +%Y%m%d-%H%M%S)"
NAME="${STAMP}-v${APP_VERSION}${LABEL:+-${LABEL}}"
DEST="${APP_ROOT}/backups/${NAME}"

mkdir -p "${DEST}"
section "Backing up to ${DEST}"

if [[ "$(service_health "${SPECTRA_DB_SERVICE}")" != "healthy" ]]; then
    warn "${SPECTRA_DB_SERVICE} is not healthy; starting it so the dump can run"
    compose up -d "${SPECTRA_DB_SERVICE}"
    wait_for_healthy "${SPECTRA_DB_SERVICE}" "${DB_WAIT_TIMEOUT:-180}"
fi

dump_database() {
    local database="$1" out="${DEST}/$1.sql.gz"
    info "pg_dump ${database}"
    if compose exec -T -e PGPASSWORD="${PG_PASSWORD}" "${SPECTRA_DB_SERVICE}" \
            pg_dump -U "${PG_USER}" -d "${database}" --clean --if-exists --no-owner \
            2>/dev/null | gzip -9 > "${out}"; then
        ok "$(basename "${out}") ($(du -h "${out}" | cut -f1))"
    else
        die "pg_dump of ${database} failed (partial file left at ${out} for inspection)"
    fi
}

dump_database "${CONTROL_DB}"

enterprise_exists="$(compose exec -T -e PGPASSWORD="${PG_PASSWORD}" "${SPECTRA_DB_SERVICE}" \
    psql -U "${PG_USER}" -d postgres -tAc \
    "SELECT 1 FROM pg_database WHERE datname = '${ENTERPRISE_DB_NAME}'" 2>/dev/null | tr -d '[:space:]')"

if [[ "${enterprise_exists}" == "1" ]]; then
    dump_database "${ENTERPRISE_DB_NAME}"
else
    warn "enterprise database ${ENTERPRISE_DB_NAME} does not exist yet; skipping"
fi

if [[ ${WITH_OBJECTS} -eq 1 ]]; then
    info "archiving object storage (this can take a while)"
    tar -czf "${DEST}/objects.tar.gz" -C "${APP_ROOT}/data" minio 2>/dev/null \
        || warn "object archive incomplete (permission denied on some files)"
    ok "objects.tar.gz ($(du -h "${DEST}/objects.tar.gz" 2>/dev/null | cut -f1))"
fi

{
    printf 'app          %s\n' "${APP_SLUG}"
    printf 'app_version  %s\n' "${APP_VERSION}"
    printf 'created_at   %s\n' "$(now_utc)"
    printf 'host         %s\n' "$(hostname)"
    printf 'control_db   %s\n' "${CONTROL_DB}"
    printf 'enterprise   %s\n' "${ENTERPRISE_DB_NAME}"
    printf 'with_objects %s\n' "${WITH_OBJECTS}"
    printf '\nchecksums\n'
    (cd "${DEST}" && sha256sum ./*.gz 2>/dev/null || true)
} > "${DEST}/manifest.txt"

if [[ "${KEEP}" -gt 0 ]]; then
    info "pruning old backups, keeping the newest ${KEEP}"
    mapfile -t stale < <(find "${APP_ROOT}/backups" -maxdepth 1 -mindepth 1 -type d | sort -r | tail -n +$(( KEEP + 1 )))
    for dir in "${stale[@]:-}"; do
        [[ -z "${dir}" ]] && continue
        rm -rf -- "${dir}"
        info "pruned $(basename "${dir}")"
    done
fi

ok "backup complete: ${DEST}"
