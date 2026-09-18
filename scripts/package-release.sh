#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Cut a full, sealed SPECTRA release bundle for an offline LAN host.
#
# Produces releases/spectra-<VERSION>/ and releases/spectra-<VERSION>-release.tar.gz
# containing everything an operator needs: images, compose file, SQL, scripts.
# No registry, no compiler and no Git are required on the target.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

usage() {
    cat <<'USAGE_EOF'
package-release.sh - build a full offline release bundle

SYNOPSIS
    ./scripts/package-release.sh [--skip-build] [--skip-pull] [--no-tarball]
    make package-release

ENVIRONMENT
    SKIP_UI_BUILD=1     do not export the built UI into the bundle
    INSTALL_ML=1        build the api/worker images with the heavy [ml] extras
    INSTALL_BACKENDS=0  build without the distributed [backends] extras
    OUTPUT_DIR=path     where to write the bundle (default: ./releases)

STEPS
    1. Read VERSION (the single source of truth for every tag).
    2. Export the built UI into ui/<VERSION>/ for provenance and rollback.
    3. docker pull every third-party image the LAN compose references.
    4. docker build spectra-api, spectra-worker, spectra-frontend and
       spectra-mock-enterprise at :<VERSION>.
    5. docker save | gzip each image into images/.
    6. Assemble the bundle: docker-compose.yml (= the LAN compose with ../db/
       rewritten to ./db/), .env.example, VERSION, CHANGELOG.md, operator
       README.md, config/, db/baseline, db/migrations, scripts/.
    7. Write release-manifest.json and CHECKSUMS.sha256, then tar + .sha256.

    The bundle deliberately contains NO Makefile: operators call ./scripts/*.sh.

OPTIONS
    --skip-build    reuse images already tagged :<VERSION> on this host
    --skip-pull     do not refresh third-party images
    --no-tarball    leave the bundle as a directory
    -h, --help      this text
USAGE_EOF
}

for arg in "$@"; do
    case "${arg}" in -h|--help) usage; exit 0 ;; esac
done

SKIP_BUILD=0
SKIP_PULL=0
NO_TARBALL=0
for arg in "$@"; do
    case "${arg}" in
        --skip-build)  SKIP_BUILD=1 ;;
        --skip-pull)   SKIP_PULL=1 ;;
        --no-tarball)  NO_TARBALL=1 ;;
        *) printf 'unknown argument: %s (try --help)\n' "${arg}" >&2; exit 1 ;;
    esac
done

# --- setup ----------------------------------------------------------------
APP_SLUG="spectra"
VERSION="$(tr -d '[:space:]' < "${REPO_ROOT}/VERSION")"
[[ -n "${VERSION}" ]] || { echo "VERSION is empty" >&2; exit 1; }

OUTPUT_DIR="${OUTPUT_DIR:-${REPO_ROOT}/releases}"
BUNDLE_NAME="${APP_SLUG}-${VERSION}"
BUNDLE_DIR="${OUTPUT_DIR}/${BUNDLE_NAME}"
LAN_COMPOSE="${REPO_ROOT}/deploy/docker-compose.lan.yml"

C_B=$'\033[1m'; C_0=$'\033[0m'
step() { printf '\n%s==> %s%s\n' "${C_B}" "$*" "${C_0}"; }
note() { printf '    %s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null || fail "docker is required"
docker compose version >/dev/null 2>&1 || fail "docker compose v2 is required"
[[ -f "${LAN_COMPOSE}" ]] || fail "missing ${LAN_COMPOSE}"

step "SPECTRA release ${VERSION}"
note "repo   ${REPO_ROOT}"
note "bundle ${BUNDLE_DIR}"

# Guard rails on the file that defines the offline contract.
if grep -qE '^[[:space:]]*build:' "${LAN_COMPOSE}"; then
    fail "the LAN compose contains a build directive - it must be image-only"
fi
if grep -qE '^version:' "${LAN_COMPOSE}"; then
    fail "the LAN compose contains the obsolete version key"
fi
if grep -qE 'image:.*:latest' "${LAN_COMPOSE}"; then
    fail "the LAN compose references a :latest tag"
fi
note "LAN compose passes the offline invariants"

rm -rf -- "${BUNDLE_DIR}"
mkdir -p "${BUNDLE_DIR}"/{images,db/baseline,db/migrations,config,certs,scripts/lib}

# The rendered LAN config is the authoritative list of images for this release.
mapfile -t ALL_IMAGES < <(
    APP_VERSION="${VERSION}" APP_ROOT=/tmp/spectra-package \
    docker compose -f "${LAN_COMPOSE}" config --images | sort -u
)
[[ ${#ALL_IMAGES[@]} -gt 0 ]] || fail "could not read the image list from the LAN compose"

APP_IMAGES=()
INFRA_IMAGES=()
for image in "${ALL_IMAGES[@]}"; do
    if [[ "${image}" == ${APP_SLUG}-* ]]; then APP_IMAGES+=("${image}"); else INFRA_IMAGES+=("${image}"); fi
done
note "${#APP_IMAGES[@]} application image(s), ${#INFRA_IMAGES[@]} third-party image(s)"

# --- 1. UI ----------------------------------------------------------------
step "1/7  UI build"
if [[ "${SKIP_UI_BUILD:-0}" == "1" ]]; then
    note "SKIP_UI_BUILD=1; the frontend image still carries the UI"
else
    note "the UI is exported from the frontend image after the build step"
fi

# --- 2. pull --------------------------------------------------------------
step "2/7  Third-party images"
if [[ ${SKIP_PULL} -eq 1 ]]; then
    note "--skip-pull"
else
    for image in "${INFRA_IMAGES[@]}"; do
        note "pull ${image}"
        docker pull --quiet "${image}" >/dev/null || fail "could not pull ${image}"
    done
fi

# --- 3. build -------------------------------------------------------------
step "3/7  Application images"
if [[ ${SKIP_BUILD} -eq 1 ]]; then
    note "--skip-build; expecting :${VERSION} tags to exist already"
else
    build_args=(
        --build-arg "INSTALL_ML=${INSTALL_ML:-0}"
        --build-arg "INSTALL_BACKENDS=${INSTALL_BACKENDS:-1}"
    )
    note "build ${APP_SLUG}-api:${VERSION}"
    docker build "${build_args[@]}" \
        -f "${REPO_ROOT}/services/api/Dockerfile" --target runtime \
        -t "${APP_SLUG}-api:${VERSION}" "${REPO_ROOT}"

    # The worker is the api image with a different entrypoint, so it must be
    # built second and layered on the tag just produced.
    note "build ${APP_SLUG}-worker:${VERSION}"
    docker build \
        --build-arg "SPECTRA_API_IMAGE=${APP_SLUG}-api:${VERSION}" \
        -f "${REPO_ROOT}/services/worker/Dockerfile" \
        -t "${APP_SLUG}-worker:${VERSION}" "${REPO_ROOT}"

    note "build ${APP_SLUG}-frontend:${VERSION}"
    docker build \
        -f "${REPO_ROOT}/apps/frontend/Dockerfile" \
        -t "${APP_SLUG}-frontend:${VERSION}" "${REPO_ROOT}"

    note "build ${APP_SLUG}-mock-enterprise:${VERSION}"
    docker build \
        -f "${REPO_ROOT}/apps/mock-enterprise/Dockerfile" \
        -t "${APP_SLUG}-mock-enterprise:${VERSION}" "${REPO_ROOT}"
fi

# Export the built UI for provenance and UI-only rollback.  SPECTRA serves its
# UI from the frontend container, so this is a record, not an nginx web root.
if [[ "${SKIP_UI_BUILD:-0}" != "1" ]]; then
    step "3b   Exporting the UI build"
    ui_dest="${BUNDLE_DIR}/ui/${VERSION}/dist/${APP_SLUG}"
    mkdir -p "${ui_dest}"
    container_id="$(docker create "${APP_SLUG}-frontend:${VERSION}" /bin/true)"
    if docker cp "${container_id}:/app/." "${ui_dest}/" >/dev/null 2>&1; then
        note "exported to ui/${VERSION}/dist/${APP_SLUG}"
    else
        note "could not export the UI from the image (continuing without it)"
    fi
    docker rm -f "${container_id}" >/dev/null 2>&1 || true
fi

# --- 4. save --------------------------------------------------------------
step "4/7  Saving images"
for image in "${APP_IMAGES[@]}" "${INFRA_IMAGES[@]}"; do
    safe="$(printf '%s' "${image}" | tr '/:' '--')"
    out="${BUNDLE_DIR}/images/${safe}.tar.gz"
    note "save ${image}"
    docker save "${image}" | gzip -1 > "${out}" || fail "docker save failed for ${image}"
done
note "$(du -sh "${BUNDLE_DIR}/images" | cut -f1) of image archives"

# --- 5. assemble ----------------------------------------------------------
step "5/7  Assembling the bundle"

# The bundle is self-contained, so ../db/ becomes ./db/.
sed -e 's|\.\./db/|./db/|g' "${LAN_COMPOSE}" > "${BUNDLE_DIR}/docker-compose.yml"
cp "${REPO_ROOT}/deploy/docker-compose.lan.gpu.yml" "${BUNDLE_DIR}/docker-compose.lan.gpu.yml"
cp "${REPO_ROOT}/deploy/.env.example"               "${BUNDLE_DIR}/.env.example"
cp "${REPO_ROOT}/VERSION"                           "${BUNDLE_DIR}/VERSION"
cp "${REPO_ROOT}/CHANGELOG.md"                      "${BUNDLE_DIR}/CHANGELOG.md"
cp -r "${REPO_ROOT}/deploy/config/." "${BUNDLE_DIR}/config/"
cp "${REPO_ROOT}/db/baseline/"*.sql                 "${BUNDLE_DIR}/db/baseline/"
cp "${REPO_ROOT}/db/migrations/"*.sql               "${BUNDLE_DIR}/db/migrations/"
cp "${REPO_ROOT}/db/migrations/README.md"           "${BUNDLE_DIR}/db/migrations/"
cp "${REPO_ROOT}/deploy/scripts/"*.sh               "${BUNDLE_DIR}/scripts/"
cp "${REPO_ROOT}/deploy/scripts/lib/"*.sh           "${BUNDLE_DIR}/scripts/lib/"
chmod +x "${BUNDLE_DIR}/scripts/"*.sh
mkdir -p "${BUNDLE_DIR}/releases/patches"
printf 'Copy patch archives here, then run ../scripts/deploy-patch.sh\n' \
    > "${BUNDLE_DIR}/releases/patches/README.txt"
printf 'Drop site TLS material here as server.crt / server.key.\n' \
    > "${BUNDLE_DIR}/certs/README.txt"
note "compose, env template, sql, config and scripts copied"

GIT_COMMIT="$(git -C "${REPO_ROOT}" rev-parse --short HEAD 2>/dev/null || echo unknown)"
BUILD_HOST="$(hostname)"
BUILD_USER="${USER:-unknown}"
CREATED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

service_json() {
    printf '    {"service": "%s", "image": "%s-%s:%s", "image_var": "SERVICE_%s_IMAGE", "container": "spectra-%s"}' \
        "$1" "${APP_SLUG}" "$1" "${VERSION}" \
        "$(printf '%s' "$1" | tr '[:lower:]-' '[:upper:]_')" "$1"
}

{
    printf '{\n'
    printf '  "type": "release",\n'
    printf '  "app": "%s",\n' "${APP_SLUG}"
    printf '  "version": "%s",\n' "${VERSION}"
    printf '  "created_at": "%s",\n' "${CREATED_AT}"
    printf '  "git_commit": "%s",\n' "${GIT_COMMIT}"
    printf '  "build_host": "%s",\n' "${BUILD_HOST}"
    printf '  "build_user": "%s",\n' "${BUILD_USER}"
    printf '  "includes_db": true,\n'
    printf '  "includes_ui": %s,\n' "$([[ -d "${BUNDLE_DIR}/ui" ]] && printf 'true' || printf 'false')"
    printf '  "service_list": "api worker frontend mock-enterprise",\n'
    printf '  "services": [\n'
    service_json api;             printf ',\n'
    service_json worker;          printf ',\n'
    service_json frontend;        printf ',\n'
    service_json mock-enterprise; printf '\n'
    printf '  ],\n'
    printf '  "third_party_images": [\n'
    for i in "${!INFRA_IMAGES[@]}"; do
        printf '    "%s"' "${INFRA_IMAGES[$i]}"
        [[ $(( i + 1 )) -lt ${#INFRA_IMAGES[@]} ]] && printf ','
        printf '\n'
    done
    printf '  ]\n'
    printf '}\n'
} > "${BUNDLE_DIR}/release-manifest.json"
note "release-manifest.json written"

# --- 6. operator README ---------------------------------------------------
step "6/7  Operator README"
cat > "${BUNDLE_DIR}/README.md" <<READMEEOF
# SPECTRA ${VERSION} - offline release bundle

Everything needed to install SPECTRA on a LAN or air-gapped host. No registry,
no compiler and no Git access are required.

Built ${CREATED_AT} from commit \`${GIT_COMMIT}\`.

## First install

\`\`\`bash
tar -xzf ${BUNDLE_NAME}-release.tar.gz
cd ${BUNDLE_NAME}
cp .env.example .env
\$EDITOR .env          # replace EVERY CHANGE_ME; set APP_ROOT and SPECTRA_PUBLIC_HOST
./scripts/deploy.sh
./scripts/verify-deployment.sh
\`\`\`

## Upgrade from an earlier version

\`\`\`bash
cp /path/to/previous-bundle/.env .env    # keeps every site-specific value
./scripts/deploy.sh                      # backs up automatically before migrating
./scripts/verify-deployment.sh
\`\`\`

## Applying a patch

\`\`\`bash
cp spectra-${VERSION}-YYYYMMDD-pN.tar.gz ./releases/patches/
./scripts/deploy-patch.sh
\`\`\`

Run \`./scripts/bootstrap-patch-support.sh\` once first if this host was
installed before patch support existed.

## Rolling back

\`\`\`bash
./scripts/rollback.sh /path/to/spectra-<PREV_VERSION>/
\`\`\`

**Rollback reverts images and the UI only. The database schema is never rolled
back automatically.** Migrations are forward-only. If the release you are
undoing changed the schema destructively, restore the pre-upgrade dump from
\`\$APP_ROOT/backups/\` *before* starting the old images - and accept that doing
so discards everything written since the backup was taken.

## Where state lives

Everything persistent is under \`\$APP_ROOT\` (default \`/opt/spectra\`):

\`\`\`
\$APP_ROOT/
├── config/                   operator-editable config (installed once, never overwritten)
├── certs/                    server.crt / server.key
├── data/                     postgres qdrant opensearch neo4j redis minio app
├── models/                   model weights
├── releases/ui/<version>/    staged UI builds, with `current` pointing at the live one
├── releases/patches/         patch inbox, and applied/ once used
├── backups/                  pg_dump snapshots
├── .deployed_version         plain text
└── .deployed-state.json      per-service images, last action, history
\`\`\`

The bundle itself stays read-only. Only \`.env\` is edited in place.

## Scripts

| Script | Purpose |
|--------|---------|
| \`deploy.sh\` | Install or upgrade |
| \`deploy-patch.sh\` | Apply a patch bundle |
| \`rollback.sh\` | Revert images and UI to a previous bundle |
| \`verify-deployment.sh\` | Probe the API and every datastore |
| \`show-state.sh\` | What is deployed, which images, what health |
| \`show-version.sh\` | Bundle vs .env vs deployed version |
| \`backup-data.sh\` | Snapshot the databases |
| \`run-migrations.sh\` | Apply baseline + migrations |
| \`import-images.sh\` | docker load the image archives |
| \`generate-ssl.sh\` | Self-signed certificate |
| \`bootstrap-patch-support.sh\` | Prepare an older host for patches |

Every script takes \`--help\`.

## Host requirements

* Docker Engine 24+ with the Compose v2 plugin
* \`vm.max_map_count >= 262144\` for OpenSearch:
  \`sudo sysctl -w vm.max_map_count=262144\` (persist it in \`/etc/sysctl.d/\`)
* ~20 GB free for indexes, plus whatever the model weights need
* Optional: NVIDIA Container Toolkit. Set \`GPU_ENABLED=1\` in \`.env\` to use it;
  leave it at 0 and set \`MODEL_PROFILE=cpu\` on a machine without a GPU.

## Verifying this bundle

\`\`\`bash
sha256sum -c ${BUNDLE_NAME}-release.tar.gz.sha256
cd ${BUNDLE_NAME} && sha256sum -c CHECKSUMS.sha256
\`\`\`
READMEEOF
note "README.md written"

# --- 7. checksums + tarball ----------------------------------------------
step "7/7  Checksums and tarball"
( cd "${BUNDLE_DIR}" && find . -type f -not -name CHECKSUMS.sha256 -print0 \
    | sort -z | xargs -0 sha256sum > CHECKSUMS.sha256 )
note "CHECKSUMS.sha256 covers $(wc -l < "${BUNDLE_DIR}/CHECKSUMS.sha256") files"

if [[ ${NO_TARBALL} -eq 1 ]]; then
    note "--no-tarball; bundle left at ${BUNDLE_DIR}"
else
    TARBALL="${OUTPUT_DIR}/${BUNDLE_NAME}-release.tar.gz"
    ( cd "${OUTPUT_DIR}" && tar -czf "$(basename "${TARBALL}")" "${BUNDLE_NAME}" )
    ( cd "${OUTPUT_DIR}" && sha256sum "$(basename "${TARBALL}")" > "$(basename "${TARBALL}").sha256" )
    note "$(du -h "${TARBALL}" | cut -f1)  ${TARBALL}"
    note "$(cat "${TARBALL}.sha256")"
fi

step "Release ${VERSION} packaged"
printf '    Transfer the tarball and its .sha256 to the operator.\n'
printf '    Validate it on a clean VM before shipping: no prior images, empty APP_ROOT.\n'
