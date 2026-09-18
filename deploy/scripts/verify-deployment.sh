#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Prove the deployment actually works: probe the API and every datastore.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

usage() {
    cat <<'USAGE_EOF'
verify-deployment.sh - end-to-end health check of a deployed SPECTRA stack

SYNOPSIS
    ./scripts/verify-deployment.sh [--quick] [--json]

WHAT IT CHECKS
    host        docker reachable, vm.max_map_count (OpenSearch), free disk,
                GPU runtime when GPU_ENABLED=1
    containers  every service running, and healthy where it has a healthcheck
    api         GET /api/health from the host AND from inside the container
    postgres    server accepting connections, control-plane tables present,
                enterprise read-only role can SELECT and CANNOT write
    qdrant      HTTP port answering
    opensearch  cluster health not red
    neo4j       bolt query returns
    redis       PING answers with the configured password
    minio       server ready and the SPECTRA bucket exists
    frontend    HTTP 200 from the analyst UI
    mock-ent.   HTTP 200 from the enterprise demo app
    version     .env APP_VERSION matches $APP_ROOT/.deployed_version

EXIT STATUS
    0  every check passed (warnings may still be printed)
    1  at least one check failed

OPTIONS
    --quick   containers and API only
    -h, --help this text
USAGE_EOF
}

handle_help "$@"

QUICK=0
for arg in "$@"; do
    case "${arg}" in
        --quick) QUICK=1 ;;
        *) die "unknown argument: ${arg} (try --help)" ;;
    esac
done

require_docker
load_env

PASS=0
FAIL=0
WARN=0

pass_check() { printf '  %s[PASS]%s %s\n' "${C_GREEN}" "${C_RESET}" "$*"; PASS=$(( PASS + 1 )); }
fail_check() { printf '  %s[FAIL]%s %s\n' "${C_RED}"   "${C_RESET}" "$*"; FAIL=$(( FAIL + 1 )); }
warn_check() { printf '  %s[WARN]%s %s\n' "${C_YELLOW}" "${C_RESET}" "$*"; WARN=$(( WARN + 1 )); }

in_container() {
    local service="$1"; shift
    compose exec -T "${service}" "$@" 2>/dev/null
}

# ===========================================================================
section "Host"
# ===========================================================================
if max_map="$(sysctl -n vm.max_map_count 2>/dev/null)"; then
    if [[ "${max_map}" -ge 262144 ]]; then
        pass_check "vm.max_map_count=${max_map}"
    else
        warn_check "vm.max_map_count=${max_map} (<262144). OpenSearch may refuse to start.
         Fix: sudo sysctl -w vm.max_map_count=262144 and persist it in /etc/sysctl.d/"
    fi
else
    warn_check "could not read vm.max_map_count"
fi

if free_kb="$(df -Pk "${APP_ROOT}" 2>/dev/null | awk 'NR==2 {print $4}')"; then
    free_gb=$(( free_kb / 1024 / 1024 ))
    if [[ "${free_gb}" -ge 20 ]]; then
        pass_check "${free_gb}GB free on ${APP_ROOT}"
    else
        warn_check "only ${free_gb}GB free on ${APP_ROOT}; indexes and models need headroom"
    fi
else
    warn_check "could not measure free space on ${APP_ROOT}"
fi

if [[ "${GPU_ENABLED:-0}" == "1" ]]; then
    if docker info 2>/dev/null | grep -qi nvidia; then
        pass_check "nvidia container runtime present"
    else
        fail_check "GPU_ENABLED=1 but the nvidia runtime is not registered with Docker"
    fi
else
    info "GPU_ENABLED=0; skipping GPU checks (MODEL_PROFILE=${MODEL_PROFILE:-unset})"
fi

# ===========================================================================
section "Containers"
# ===========================================================================
for service in "${SPECTRA_INFRA_SERVICES[@]}" "${SPECTRA_APP_SERVICES[@]}"; do
    status="$(service_health "${service}")"
    case "${status}" in
        healthy)  pass_check "${service} is healthy" ;;
        running)  warn_check "${service} is running but reports no healthcheck status yet" ;;
        starting) warn_check "${service} is still starting" ;;
        absent)   fail_check "${service} has no container in project ${COMPOSE_PROJECT_NAME}" ;;
        *)        fail_check "${service} is ${status}" ;;
    esac
done

# ===========================================================================
section "API"
# ===========================================================================
API_URL_HOST="http://127.0.0.1:${API_PUBLISHED_PORT:-8000}/api/health"
if command -v curl >/dev/null 2>&1; then
    if body="$(curl -fsSk --max-time 15 "${API_URL_HOST}" 2>/dev/null)"; then
        pass_check "GET ${API_URL_HOST}"
        printf '         %s\n' "$(printf '%s' "${body}" | head -c 300)"
    else
        fail_check "GET ${API_URL_HOST} failed (published port not answering)"
    fi
else
    warn_check "curl not installed on the host; skipping the external API probe"
fi

if in_container api curl -fsSk --max-time 15 "http://127.0.0.1:${API_PORT:-8000}/api/health" >/dev/null; then
    pass_check "GET /api/health from inside the api container"
else
    fail_check "the api container cannot serve /api/health to itself"
fi

[[ ${QUICK} -eq 1 ]] && { section "Summary"; printf '  %d passed, %d failed, %d warnings\n' "${PASS}" "${FAIL}" "${WARN}"; exit $(( FAIL > 0 ? 1 : 0 )); }

# ===========================================================================
section "PostgreSQL"
# ===========================================================================
PG_USER="${POSTGRES_USER:-spectra}"
CONTROL_DB="${POSTGRES_DB:-spectra}"
ENTERPRISE_DB_NAME="${ENTERPRISE_DB:-spectra_enterprise}"
READONLY_USER="${ENTERPRISE_READONLY_USER:-spectra_readonly}"

pg() {
    local database="$1" sql="$2"
    compose exec -T -e PGPASSWORD="${POSTGRES_PASSWORD:-}" "${SPECTRA_DB_SERVICE}" \
        psql -U "${PG_USER}" -d "${database}" -tAc "${sql}" 2>/dev/null | tr -d '[:space:]'
}

if in_container "${SPECTRA_DB_SERVICE}" pg_isready -U "${PG_USER}" -d "${CONTROL_DB}" >/dev/null; then
    pass_check "postgres accepting connections"
else
    fail_check "pg_isready failed"
fi

tables="$(pg "${CONTROL_DB}" "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")"
if [[ "${tables:-0}" -ge 10 ]]; then
    pass_check "control plane has ${tables} tables in ${CONTROL_DB}"
else
    fail_check "control plane has only ${tables:-0} tables; run ./scripts/run-migrations.sh"
fi

applied="$(pg "${CONTROL_DB}" "SELECT count(*) FROM spectra_schema_history")"
if [[ "${applied:-0}" -ge 1 ]]; then
    pass_check "${applied} schema file(s) recorded in spectra_schema_history"
else
    fail_check "spectra_schema_history is empty or missing"
fi

ent_tables="$(pg "${ENTERPRISE_DB_NAME}" "SELECT count(*) FROM information_schema.tables WHERE table_schema='enterprise'")"
if [[ "${ent_tables:-0}" -ge 4 ]]; then
    pass_check "enterprise schema has ${ent_tables} tables in ${ENTERPRISE_DB_NAME}"
else
    fail_check "enterprise schema incomplete (${ent_tables:-0} tables)"
fi

# The Database Agent's identity must be able to read and must not be able to write.
ro_select="$(compose exec -T -e PGPASSWORD="${ENTERPRISE_READONLY_PASSWORD:-}" "${SPECTRA_DB_SERVICE}" \
    psql -U "${READONLY_USER}" -d "${ENTERPRISE_DB_NAME}" -tAc \
    "SELECT count(*) FROM enterprise.customers" 2>/dev/null | tr -d '[:space:]')"
if [[ -n "${ro_select}" ]]; then
    pass_check "${READONLY_USER} can SELECT (${ro_select} customers visible)"
else
    fail_check "${READONLY_USER} cannot SELECT from enterprise.customers"
fi

if compose exec -T -e PGPASSWORD="${ENTERPRISE_READONLY_PASSWORD:-}" "${SPECTRA_DB_SERVICE}" \
        psql -U "${READONLY_USER}" -d "${ENTERPRISE_DB_NAME}" -tAc \
        "INSERT INTO enterprise.customers (customer_id, legal_name, display_name) VALUES ('VERIFY-RW','x','x')" \
        >/dev/null 2>&1; then
    fail_check "${READONLY_USER} was able to INSERT - the read-only role is not read-only"
else
    pass_check "${READONLY_USER} is refused write access (expected)"
fi

# ===========================================================================
section "Datastores"
# ===========================================================================
if in_container qdrant bash -c "exec 3<>/dev/tcp/127.0.0.1/${QDRANT_PORT:-6333}"; then
    pass_check "qdrant answering on ${QDRANT_PORT:-6333}"
else
    fail_check "qdrant is not answering on ${QDRANT_PORT:-6333}"
fi

os_status="$(in_container opensearch curl -fsS "http://127.0.0.1:${OPENSEARCH_PORT:-9200}/_cluster/health" \
    | sed -n 's/.*"status":"\([a-z]*\)".*/\1/p')"
case "${os_status}" in
    green|yellow) pass_check "opensearch cluster status ${os_status} (yellow is normal for a single node)" ;;
    red)          fail_check "opensearch cluster status red" ;;
    *)            fail_check "opensearch cluster health unreadable" ;;
esac

if in_container neo4j cypher-shell -u "${NEO4J_USER:-neo4j}" -p "${NEO4J_PASSWORD:-}" "RETURN 1" >/dev/null; then
    pass_check "neo4j answering bolt queries"
else
    fail_check "neo4j did not answer a trivial cypher query"
fi

if in_container redis redis-cli -a "${REDIS_PASSWORD:-}" --no-auth-warning ping | grep -q PONG; then
    pass_check "redis PONG"
else
    fail_check "redis did not answer PING"
fi

if in_container minio mc ready local >/dev/null; then
    pass_check "minio ready"
else
    fail_check "minio is not ready"
fi

if in_container minio mc ls "local/${MINIO_BUCKET:-spectra}" >/dev/null 2>&1 \
   || in_container minio mc stat "local/${MINIO_BUCKET:-spectra}" >/dev/null 2>&1; then
    pass_check "minio bucket ${MINIO_BUCKET:-spectra} exists"
else
    warn_check "could not confirm bucket ${MINIO_BUCKET:-spectra}; check the minio-init container logs"
fi

# ===========================================================================
section "Web tiers"
# ===========================================================================
check_web() {
    local label="$1" service="$2" port="$3"
    if in_container "${service}" node -e \
        "fetch('http://127.0.0.1:${port}/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"; then
        pass_check "${label} responding on ${port}"
    else
        fail_check "${label} did not respond on ${port}"
    fi
}
check_web "analyst frontend"   frontend        "${FRONTEND_PORT:-3000}"
check_web "mock enterprise app" mock-enterprise "${MOCK_ENTERPRISE_PORT:-3001}"

# ===========================================================================
section "Version"
# ===========================================================================
deployed="$(deployed_version)"
if [[ -z "${deployed}" ]]; then
    fail_check "$(version_file) is missing - this stack was not deployed by deploy.sh"
elif [[ "${deployed}" == "${APP_VERSION}" ]]; then
    pass_check "deployed version ${deployed} matches .env"
else
    fail_check "deployed version ${deployed} does not match .env APP_VERSION=${APP_VERSION}"
fi

# ===========================================================================
section "Summary"
# ===========================================================================
printf '  %d passed, %d failed, %d warnings\n' "${PASS}" "${FAIL}" "${WARN}"
if [[ ${FAIL} -gt 0 ]]; then
    err "deployment verification FAILED"
    log "  logs:  ./scripts/show-state.sh --logs <service>"
    exit 1
fi
ok "deployment verified"
