#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Cut a SPECTRA patch bundle: a subset of services (+ migrations, + UI) applied
# on top of a host already running the same base VERSION.
#
# Patches never carry third-party images - the host already has them.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

usage() {
    cat <<'USAGE_EOF'
package-patch.sh - build a patch bundle for services that changed

SYNOPSIS
    SVC='api worker' ./scripts/package-patch.sh
    make package-patch SVC='api worker'
    make package-patch SVC=api DB=1
    make package-patch UI=1
    make package-patch SVC=frontend DB=1 UI=1

ENVIRONMENT
    SVC="api worker"   services to rebuild and ship
                       (api | worker | frontend | mock-enterprise)
    DB=1               include db/migrations so the patch runs them
    UI=1               include the built UI and the frontend + mock-enterprise images
    SKIP_UI_BUILD=1    do not export the UI even with UI=1
    OUTPUT_DIR=path    where to write (default: ./releases/patches)

PATCH ID
    <BASE_VERSION>-YYYYMMDD-pN

    N is computed by scanning releases/, releases/patches/ and
    releases/patches/applied/ for the highest sequence already used for this
    base version and day, then adding one.  It is NEVER assigned by hand, and
    deleting an archive does not free its number - the scanner also looks at
    applied/, so ids are never reused.

    Patch images are tagged with the PATCH ID, not the base version:
        spectra-api:1.0.0-20260917-p1

OPTIONS
    --skip-build   reuse images already tagged with the computed patch id
    --no-tarball   leave the bundle as a directory
    -h, --help     this text
USAGE_EOF
}

for arg in "$@"; do
    case "${arg}" in -h|--help) usage; exit 0 ;; esac
done

SKIP_BUILD=0
NO_TARBALL=0
for arg in "$@"; do
    case "${arg}" in
        --skip-build) SKIP_BUILD=1 ;;
        --no-tarball) NO_TARBALL=1 ;;
        *) printf 'unknown argument: %s (try --help)\n' "${arg}" >&2; exit 1 ;;
    esac
done

APP_SLUG="spectra"
BASE_VERSION="$(tr -d '[:space:]' < "${REPO_ROOT}/VERSION")"
RELEASES_DIR="${REPO_ROOT}/releases"
OUTPUT_DIR="${OUTPUT_DIR:-${RELEASES_DIR}/patches}"
INCLUDE_DB="${DB:-0}"
INCLUDE_UI="${UI:-0}"
SERVICES="${SVC:-}"

C_B=$'\033[1m'; C_0=$'\033[0m'
step() { printf '\n%s==> %s%s\n' "${C_B}" "$*" "${C_0}"; }
note() { printf '    %s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null || fail "docker is required"

# UI=1 implies the two Next.js services.
if [[ "${INCLUDE_UI}" == "1" ]]; then
    for svc in frontend mock-enterprise; do
        [[ " ${SERVICES} " == *" ${svc} "* ]] || SERVICES="${SERVICES} ${svc}"
    done
fi
SERVICES="$(printf '%s' "${SERVICES}" | tr -s ' ' | sed -e 's/^ //' -e 's/ $//')"

[[ -n "${SERVICES}" || "${INCLUDE_DB}" == "1" ]] \
    || fail "nothing to ship. Set SVC='api worker', and/or DB=1, and/or UI=1 (try --help)"

for svc in ${SERVICES}; do
    case "${svc}" in
        api|worker|frontend|mock-enterprise) ;;
        *) fail "unknown service '${svc}'. Valid: api worker frontend mock-enterprise" ;;
    esac
done

# --- patch id -------------------------------------------------------------
step "Computing the patch id"
DATE_STAMP="$(date -u +%Y%m%d)"
PREFIX="${APP_SLUG}-${BASE_VERSION}-${DATE_STAMP}-p"

highest=0
for dir in "${RELEASES_DIR}" "${RELEASES_DIR}/patches" "${RELEASES_DIR}/patches/applied"; do
    [[ -d "${dir}" ]] || continue
    while IFS= read -r entry; do
        [[ -z "${entry}" ]] && continue
        name="$(basename "${entry}")"
        seq="$(printf '%s' "${name}" | sed -n "s|^${PREFIX}\([0-9]\{1,\}\).*|\1|p")"
        [[ -n "${seq}" ]] || continue
        if (( seq > highest )); then highest="${seq}"; fi
    done < <(find "${dir}" -maxdepth 1 -mindepth 1 \( -name "${PREFIX}*" \) 2>/dev/null)
done

SEQUENCE=$(( highest + 1 ))
PATCH_ID="${BASE_VERSION}-${DATE_STAMP}-p${SEQUENCE}"
BUNDLE_NAME="${APP_SLUG}-${PATCH_ID}"
BUNDLE_DIR="${OUTPUT_DIR}/${BUNDLE_NAME}"

note "base version ${BASE_VERSION}"
note "patch id     ${PATCH_ID}  (highest existing sequence today: ${highest})"
note "services     ${SERVICES:-none}"
note "include db   ${INCLUDE_DB}"
note "include ui   ${INCLUDE_UI}"

if [[ -e "${BUNDLE_DIR}" ]]; then
    fail "${BUNDLE_DIR} already exists - the sequence scan disagrees with the filesystem"
fi

mkdir -p "${BUNDLE_DIR}/images"

# --- build ----------------------------------------------------------------
step "Building patched images"
build_service() {
    local svc="$1" tag="${APP_SLUG}-$1:${PATCH_ID}"
    case "${svc}" in
        api)
            docker build \
                --build-arg "INSTALL_ML=${INSTALL_ML:-0}" \
                --build-arg "INSTALL_BACKENDS=${INSTALL_BACKENDS:-1}" \
                -f "${REPO_ROOT}/services/api/Dockerfile" --target runtime \
                -t "${tag}" "${REPO_ROOT}"
            ;;
        worker)
            # The worker layers on an api image; build one at the patch id if the
            # patch does not already ship api.
            if [[ " ${SERVICES} " != *" api "* ]]; then
                docker build \
                    --build-arg "INSTALL_ML=${INSTALL_ML:-0}" \
                    --build-arg "INSTALL_BACKENDS=${INSTALL_BACKENDS:-1}" \
                    -f "${REPO_ROOT}/services/api/Dockerfile" --target runtime \
                    -t "${APP_SLUG}-api:${PATCH_ID}" "${REPO_ROOT}"
            fi
            docker build \
                --build-arg "SPECTRA_API_IMAGE=${APP_SLUG}-api:${PATCH_ID}" \
                -f "${REPO_ROOT}/services/worker/Dockerfile" \
                -t "${tag}" "${REPO_ROOT}"
            ;;
        frontend)
            docker build -f "${REPO_ROOT}/apps/frontend/Dockerfile" -t "${tag}" "${REPO_ROOT}/apps/frontend"
            ;;
        mock-enterprise)
            docker build -f "${REPO_ROOT}/apps/mock-enterprise/Dockerfile" -t "${tag}" "${REPO_ROOT}/apps/mock-enterprise"
            ;;
    esac
}

if [[ ${SKIP_BUILD} -eq 1 ]]; then
    note "--skip-build; expecting :${PATCH_ID} tags to exist already"
else
    # api first: the worker image is derived from it.
    for svc in api worker frontend mock-enterprise; do
        [[ " ${SERVICES} " == *" ${svc} "* ]] || continue
        note "build ${APP_SLUG}-${svc}:${PATCH_ID}"
        build_service "${svc}"
    done
fi

# --- save -----------------------------------------------------------------
step "Saving images"
for svc in ${SERVICES}; do
    image="${APP_SLUG}-${svc}:${PATCH_ID}"
    note "save ${image}"
    docker save "${image}" | gzip -1 > "${BUNDLE_DIR}/images/${APP_SLUG}-${svc}-${PATCH_ID}.tar.gz" \
        || fail "docker save failed for ${image}"
done
if [[ -n "${SERVICES}" ]]; then
    note "$(du -sh "${BUNDLE_DIR}/images" | cut -f1) of image archives"
fi

# --- image pins -----------------------------------------------------------
# deploy-patch.sh merges this into the live .env; the immutable compose file
# reads SERVICE_<SVC>_IMAGE and starts the patched image without being edited.
step "Writing patch.env"
{
    printf '# Image pins applied by deploy-patch.sh for patch %s\n' "${PATCH_ID}"
    for svc in ${SERVICES}; do
        printf 'SERVICE_%s_IMAGE=%s-%s:%s\n' \
            "$(printf '%s' "${svc}" | tr '[:lower:]-' '[:upper:]_')" "${APP_SLUG}" "${svc}" "${PATCH_ID}"
    done
} > "${BUNDLE_DIR}/patch.env"
sed 's/^/    /' "${BUNDLE_DIR}/patch.env"

# --- db -------------------------------------------------------------------
if [[ "${INCLUDE_DB}" == "1" ]]; then
    step "Including migrations"
    mkdir -p "${BUNDLE_DIR}/db/migrations"
    cp "${REPO_ROOT}/db/migrations/"*.sql "${BUNDLE_DIR}/db/migrations/"
    note "$(find "${BUNDLE_DIR}/db/migrations" -name '*.sql' | wc -l) migration file(s)"
    note "already-applied files are skipped by run-migrations.sh at apply time"
fi

# --- ui -------------------------------------------------------------------
if [[ "${INCLUDE_UI}" == "1" && "${SKIP_UI_BUILD:-0}" != "1" ]]; then
    step "Exporting the UI build"
    ui_dest="${BUNDLE_DIR}/ui/dist/${APP_SLUG}"
    mkdir -p "${ui_dest}"
    container_id="$(docker create "${APP_SLUG}-frontend:${PATCH_ID}" /bin/true)"
    if docker cp "${container_id}:/app/." "${ui_dest}/" >/dev/null 2>&1; then
        note "exported to ui/dist/${APP_SLUG}"
    else
        note "could not export the UI from the image (continuing without it)"
    fi
    docker rm -f "${container_id}" >/dev/null 2>&1 || true
fi

# --- manifest -------------------------------------------------------------
step "Writing patch-manifest.json"
GIT_COMMIT="$(git -C "${REPO_ROOT}" rev-parse --short HEAD 2>/dev/null || echo unknown)"
CREATED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

{
    printf '{\n'
    printf '  "type": "patch",\n'
    printf '  "app": "%s",\n' "${APP_SLUG}"
    printf '  "patch_id": "%s",\n' "${PATCH_ID}"
    printf '  "base_version": "%s",\n' "${BASE_VERSION}"
    printf '  "sequence": %d,\n' "${SEQUENCE}"
    printf '  "created_at": "%s",\n' "${CREATED_AT}"
    printf '  "git_commit": "%s",\n' "${GIT_COMMIT}"
    printf '  "build_host": "%s",\n' "$(hostname)"
    printf '  "build_user": "%s",\n' "${USER:-unknown}"
    printf '  "includes_db": %s,\n' "$([[ "${INCLUDE_DB}" == "1" ]] && printf 'true' || printf 'false')"
    printf '  "includes_ui": %s,\n' "$([[ "${INCLUDE_UI}" == "1" ]] && printf 'true' || printf 'false')"
    printf '  "service_list": "%s",\n' "${SERVICES}"
    printf '  "services": [\n'
    first=1
    for svc in ${SERVICES}; do
        [[ ${first} -eq 1 ]] && first=0 || printf ',\n'
        printf '    {"service": "%s", "image": "%s-%s:%s", "image_var": "SERVICE_%s_IMAGE", "container": "spectra-%s"}' \
            "${svc}" "${APP_SLUG}" "${svc}" "${PATCH_ID}" \
            "$(printf '%s' "${svc}" | tr '[:lower:]-' '[:upper:]_')" "${svc}"
    done
    printf '\n  ]\n'
    printf '}\n'
} > "${BUNDLE_DIR}/patch-manifest.json"
sed 's/^/    /' "${BUNDLE_DIR}/patch-manifest.json"

cat > "${BUNDLE_DIR}/README.txt" <<READMEEOF
SPECTRA patch ${PATCH_ID}
Base version: ${BASE_VERSION}   Services: ${SERVICES:-none}   DB: ${INCLUDE_DB}   UI: ${INCLUDE_UI}

Apply it from the LIVE deploy directory on the target host - not from a fresh
extract of the release bundle:

    cp ${BUNDLE_NAME}.tar.gz <deploy-dir>/releases/patches/
    cd <deploy-dir>
    ./scripts/deploy-patch.sh

The host must already be running ${BASE_VERSION}. Run
./scripts/bootstrap-patch-support.sh once first if it was installed before
patch support existed.

The database is never rolled back automatically. If this patch carries
migrations, deploy-patch.sh takes a backup into \$APP_ROOT/backups first.
READMEEOF

# --- checksums + tarball --------------------------------------------------
step "Checksums and tarball"
( cd "${BUNDLE_DIR}" && find . -type f -not -name CHECKSUMS.sha256 -print0 \
    | sort -z | xargs -0 sha256sum > CHECKSUMS.sha256 )
note "CHECKSUMS.sha256 covers $(wc -l < "${BUNDLE_DIR}/CHECKSUMS.sha256") files"

if [[ ${NO_TARBALL} -eq 1 ]]; then
    note "--no-tarball; bundle left at ${BUNDLE_DIR}"
else
    TARBALL="${OUTPUT_DIR}/${BUNDLE_NAME}.tar.gz"
    ( cd "${OUTPUT_DIR}" && tar -czf "$(basename "${TARBALL}")" "${BUNDLE_NAME}" )
    ( cd "${OUTPUT_DIR}" && sha256sum "$(basename "${TARBALL}")" > "$(basename "${TARBALL}").sha256" )
    note "$(du -h "${TARBALL}" | cut -f1)  ${TARBALL}"
fi

step "Patch ${PATCH_ID} packaged"
printf '    Ship the tarball to the operator; it applies on top of %s.\n' "${BASE_VERSION}"
