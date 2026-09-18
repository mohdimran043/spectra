#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Apply the SPECTRA database baseline and the ordered migration stream.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

usage() {
    cat <<'USAGE_EOF'
run-migrations.sh - apply database baseline and migrations

USAGE
    ./scripts/run-migrations.sh [--dry-run] [--baseline-only] [--migrations-only]

WHAT IT DOES
    1. Waits for the postgres service to be healthy.
    2. Creates the enterprise demo database if it does not exist.
    3. Ensures spectra_schema_history exists in every target database.
    4. On a GREENFIELD database only, applies db/baseline/*.sql in order.
    5. Applies every db/migrations/*.sql not already recorded, in filename order.

    Files already recorded in spectra_schema_history are skipped.  If a recorded
    file's checksum no longer matches what is on disk, the script stops: a
    shipped migration must never be edited (see db/migrations/README.md).

    Each SQL file declares its target database with a comment:
        -- spectra:target=control      (default)
        -- spectra:target=enterprise

OPTIONS
    --dry-run           list what would be applied, change nothing
    --baseline-only     apply baseline files only
    --migrations-only   apply the migration stream only
    -h, --help          this text

NOTES
    Migrations are forward-only.  rollback.sh reverts images and UI, never the
    database schema - restore from $APP_ROOT/backups if you need the old shape.
USAGE_EOF
}

handle_help "$@"

DRY_RUN=0
DO_BASELINE=1
DO_MIGRATIONS=1
for arg in "$@"; do
    case "${arg}" in
        --dry-run)         DRY_RUN=1 ;;
        --baseline-only)   DO_MIGRATIONS=0 ;;
        --migrations-only) DO_BASELINE=0 ;;
        *) die "unknown argument: ${arg} (try --help)" ;;
    esac
done

require_docker
load_env

CONTROL_DB="${POSTGRES_DB:-spectra}"
ENTERPRISE_DB_NAME="${ENTERPRISE_DB:-spectra_enterprise}"
PG_USER="${POSTGRES_USER:-spectra}"
PG_PASSWORD="${POSTGRES_PASSWORD:-}"
READONLY_USER="${ENTERPRISE_READONLY_USER:-spectra_readonly}"
READONLY_PASSWORD="${ENTERPRISE_READONLY_PASSWORD:-}"
STATEMENT_TIMEOUT="${SQL_QUERY_TIMEOUT_SECONDS:-10}s"

[[ -n "${PG_PASSWORD}" ]]       || die "POSTGRES_PASSWORD is not set in ${ENV_FILE}"
[[ -n "${READONLY_PASSWORD}" ]] || die "ENTERPRISE_READONLY_PASSWORD is not set in ${ENV_FILE}"
[[ -d "${DB_DIR}" ]]            || die "database directory not found: ${DB_DIR}"

# --- psql plumbing ---------------------------------------------------------
# All SQL runs inside the postgres container, so the host needs no client.
psql_scalar() {
    local database="$1" sql="$2"
    compose exec -T -e PGPASSWORD="${PG_PASSWORD}" "${SPECTRA_DB_SERVICE}" \
        psql -v ON_ERROR_STOP=1 -U "${PG_USER}" -d "${database}" -tAc "${sql}" 2>/dev/null | tr -d '[:space:]'
}

psql_command() {
    local database="$1" sql="$2"
    compose exec -T -e PGPASSWORD="${PG_PASSWORD}" "${SPECTRA_DB_SERVICE}" \
        psql -v ON_ERROR_STOP=1 -U "${PG_USER}" -d "${database}" -c "${sql}" >/dev/null
}

psql_file() {
    local database="$1" file="$2"
    compose exec -T -e PGPASSWORD="${PG_PASSWORD}" "${SPECTRA_DB_SERVICE}" \
        psql -v ON_ERROR_STOP=1 -U "${PG_USER}" -d "${database}" \
             -v "readonly_user=${READONLY_USER}" \
             -v "readonly_password=${READONLY_PASSWORD}" \
             -v "owner_role=${PG_USER}" \
             -v "statement_timeout=${STATEMENT_TIMEOUT}" \
             -f - < "${file}"
}

file_target_db() {
    local file="$1" target
    target="$(grep -m1 -oE '^--[[:space:]]*spectra:target=[a-z_]+' "${file}" | sed 's/.*=//' || true)"
    case "${target}" in
        enterprise) printf '%s' "${ENTERPRISE_DB_NAME}" ;;
        *)          printf '%s' "${CONTROL_DB}" ;;
    esac
}

file_checksum() { sha256sum "$1" | awk '{print $1}'; }

ensure_history_table() {
    local database="$1"
    psql_command "${database}" "
        CREATE TABLE IF NOT EXISTS spectra_schema_history (
            filename    text PRIMARY KEY,
            kind        text        NOT NULL,
            checksum    text        NOT NULL,
            app_version text,
            applied_at  timestamptz NOT NULL DEFAULT now()
        );"
}

record_file() {
    local database="$1" filename="$2" kind="$3" checksum="$4"
    psql_command "${database}" "
        INSERT INTO spectra_schema_history (filename, kind, checksum, app_version)
        VALUES ('${filename}', '${kind}', '${checksum}', '${APP_VERSION}')
        ON CONFLICT (filename) DO NOTHING;"
}

recorded_checksum() {
    local database="$1" filename="$2"
    psql_scalar "${database}" \
        "SELECT checksum FROM spectra_schema_history WHERE filename = '${filename}'"
}

# --- preflight -------------------------------------------------------------
section "Database migrations"
info "control plane database : ${CONTROL_DB}"
info "enterprise database    : ${ENTERPRISE_DB_NAME}"
info "sql directory          : ${DB_DIR}"

if [[ "$(service_health "${SPECTRA_DB_SERVICE}")" == "absent" ]]; then
    info "starting ${SPECTRA_DB_SERVICE}"
    [[ ${DRY_RUN} -eq 1 ]] || compose up -d "${SPECTRA_DB_SERVICE}"
fi
[[ ${DRY_RUN} -eq 1 ]] || wait_for_healthy "${SPECTRA_DB_SERVICE}" "${DB_WAIT_TIMEOUT:-180}"

if [[ ${DRY_RUN} -eq 1 ]]; then
    info "dry run: listing files only"
    find "${DB_DIR}/baseline" -maxdepth 1 -name '*.sql' 2>/dev/null | sort | sed 's/^/  baseline   /'
    find "${DB_DIR}/migrations" -maxdepth 1 -name '*.sql' 2>/dev/null | sort | sed 's/^/  migration  /'
    exit 0
fi

# --- enterprise database ---------------------------------------------------
if [[ "$(psql_scalar postgres "SELECT 1 FROM pg_database WHERE datname = '${ENTERPRISE_DB_NAME}'")" != "1" ]]; then
    info "creating database ${ENTERPRISE_DB_NAME}"
    psql_command postgres "CREATE DATABASE \"${ENTERPRISE_DB_NAME}\" OWNER \"${PG_USER}\""
    ok "created ${ENTERPRISE_DB_NAME}"
else
    ok "database ${ENTERPRISE_DB_NAME} already exists"
fi

ensure_history_table "${CONTROL_DB}"
ensure_history_table "${ENTERPRISE_DB_NAME}"

# --- baseline --------------------------------------------------------------
apply_sql_file() {
    local file="$1" kind="$2"
    local filename database checksum recorded
    filename="$(basename "${file}")"
    database="$(file_target_db "${file}")"
    checksum="$(file_checksum "${file}")"
    recorded="$(recorded_checksum "${database}" "${filename}")"

    if [[ -n "${recorded}" ]]; then
        if [[ "${recorded}" != "${checksum}" ]]; then
            err "${filename} was applied to ${database} with a different checksum."
            err "  recorded: ${recorded}"
            err "  on disk : ${checksum}"
            die "a shipped SQL file was edited. Ship a NEW migration instead; never modify an applied one."
        fi
        ok "skip ${filename} (already applied to ${database})"
        return 0
    fi

    info "applying ${kind} ${filename} -> ${database}"
    psql_file "${database}" "${file}"
    record_file "${database}" "${filename}" "${kind}" "${checksum}"
    ok "applied ${filename}"
}

if [[ ${DO_BASELINE} -eq 1 && -d "${DB_DIR}/baseline" ]]; then
    section "Baseline"
    # Greenfield = the control plane has no SPECTRA tables yet.  On an existing
    # database the baseline is recorded as already-applied instead of being run,
    # so a live schema is never touched by a greenfield script.
    control_populated="$(psql_scalar "${CONTROL_DB}" "SELECT CASE WHEN to_regclass('public.sources') IS NULL THEN 0 ELSE 1 END")"
    while IFS= read -r file; do
        [[ -z "${file}" ]] && continue
        if [[ "${control_populated}" == "1" && "$(file_target_db "${file}")" == "${CONTROL_DB}" ]]; then
            filename="$(basename "${file}")"
            if [[ -z "$(recorded_checksum "${CONTROL_DB}" "${filename}")" ]]; then
                warn "${filename} not recorded but the control plane already has tables;"
                warn "recording it as applied without running it (existing schema left alone)"
                record_file "${CONTROL_DB}" "${filename}" "baseline-assumed" "$(file_checksum "${file}")"
            else
                ok "skip ${filename} (already applied to ${CONTROL_DB})"
            fi
            continue
        fi
        apply_sql_file "${file}" "baseline"
    done < <(find "${DB_DIR}/baseline" -maxdepth 1 -name '*.sql' | sort)
fi

# --- migrations ------------------------------------------------------------
if [[ ${DO_MIGRATIONS} -eq 1 && -d "${DB_DIR}/migrations" ]]; then
    section "Migrations"
    applied_count=0
    while IFS= read -r file; do
        [[ -z "${file}" ]] && continue
        before="$(recorded_checksum "$(file_target_db "${file}")" "$(basename "${file}")")"
        apply_sql_file "${file}" "migration"
        [[ -z "${before}" ]] && applied_count=$(( applied_count + 1 ))
    done < <(find "${DB_DIR}/migrations" -maxdepth 1 -name '*.sql' | sort)
    ok "${applied_count} new migration(s) applied"
fi

section "Done"
ok "database is at ${APP_VERSION}"
