#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Load every image tarball shipped in this bundle into the local Docker daemon.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

usage() {
    cat <<'USAGE_EOF'
import-images.sh - docker load every image in the bundle

SYNOPSIS
    ./scripts/import-images.sh [DIRECTORY]

    DIRECTORY defaults to ./images next to docker-compose.yml.

WHAT IT DOES
    Runs `docker load` on every *.tar.gz (and *.tar) in the directory and prints
    the tags that were loaded.  Safe to rerun: loading an image that is already
    present is a no-op.

    deploy.sh and deploy-patch.sh call this for you; run it directly only when
    pre-seeding a host ahead of a maintenance window.

OPTIONS
    -h, --help   this text
USAGE_EOF
}

handle_help "$@"
require_docker

TARGET_DIR="${1:-${IMAGES_DIR}}"
[[ -d "${TARGET_DIR}" ]] || die "image directory not found: ${TARGET_DIR}"

mapfile -t archives < <(find "${TARGET_DIR}" -maxdepth 1 \( -name '*.tar.gz' -o -name '*.tar' \) | sort)
[[ ${#archives[@]} -gt 0 ]] || die "no image archives found in ${TARGET_DIR}"

section "Loading ${#archives[@]} image archive(s) from ${TARGET_DIR}"
for archive in "${archives[@]}"; do
    info "$(basename "${archive}")"
    if [[ "${archive}" == *.gz ]]; then
        gunzip -c "${archive}" | docker load | sed 's/^/     /'
    else
        docker load -i "${archive}" | sed 's/^/     /'
    fi
done
ok "all images loaded"
