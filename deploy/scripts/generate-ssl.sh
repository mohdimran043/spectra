#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Generate a self-signed TLS certificate for this host, if one is not present.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

usage() {
    cat <<'USAGE_EOF'
generate-ssl.sh - create a self-signed certificate under $APP_ROOT/certs

SYNOPSIS
    ./scripts/generate-ssl.sh [--force] [--cn HOSTNAME] [--days N]

WHAT IT DOES
    Creates $APP_ROOT/certs/server.crt and server.key if they do not exist.
    Existing files are never overwritten unless --force is given.

    The certificate covers the CN plus localhost and 127.0.0.1 as SANs.
    SPECTRA serves plain HTTP by default; point uvicorn at these files with
    SPECTRA_UVICORN_EXTRA_ARGS in .env, or terminate TLS at your own proxy.

    *** A self-signed certificate is for LAN bring-up and testing only.       ***
    *** Replace server.crt/server.key with certificates issued by your own CA ***
    *** before this deployment carries real investigation material.           ***

OPTIONS
    --force        overwrite an existing certificate (the old pair is backed up)
    --cn HOST      common name; defaults to SPECTRA_PUBLIC_HOST, then hostname
    --days N       validity in days (default 825)
    -h, --help     this text
USAGE_EOF
}

handle_help "$@"
require_cmd openssl
load_env

FORCE=0
CERT_CN="${SPECTRA_PUBLIC_HOST:-$(hostname -f 2>/dev/null || hostname)}"
CERT_DAYS=825

while [[ $# -gt 0 ]]; do
    case "$1" in
        --force) FORCE=1; shift ;;
        --cn)    CERT_CN="${2:?--cn needs a value}"; shift 2 ;;
        --days)  CERT_DAYS="${2:?--days needs a value}"; shift 2 ;;
        *)       die "unknown argument: $1 (try --help)" ;;
    esac
done

CERT_DIR="${APP_ROOT}/certs"
CERT_FILE="${CERT_DIR}/server.crt"
KEY_FILE="${CERT_DIR}/server.key"

mkdir -p "${CERT_DIR}"

if [[ -f "${CERT_FILE}" && -f "${KEY_FILE}" && ${FORCE} -eq 0 ]]; then
    ok "certificate already present: ${CERT_FILE}"
    openssl x509 -in "${CERT_FILE}" -noout -subject -enddate 2>/dev/null | sed 's/^/     /' || true
    exit 0
fi

if [[ -f "${CERT_FILE}" ]]; then
    backup_suffix="$(date -u +%Y%m%d%H%M%S)"
    mv "${CERT_FILE}" "${CERT_FILE}.${backup_suffix}.bak"
    [[ -f "${KEY_FILE}" ]] && mv "${KEY_FILE}" "${KEY_FILE}.${backup_suffix}.bak"
    warn "previous certificate moved aside with suffix .${backup_suffix}.bak"
fi

section "Generating a self-signed certificate for ${CERT_CN}"
openssl req -x509 -newkey rsa:4096 -sha256 -nodes \
    -days "${CERT_DAYS}" \
    -keyout "${KEY_FILE}" \
    -out "${CERT_FILE}" \
    -subj "/CN=${CERT_CN}/O=SPECTRA/OU=LAN deployment" \
    -addext "subjectAltName=DNS:${CERT_CN},DNS:localhost,IP:127.0.0.1" \
    >/dev/null 2>&1

chmod 640 "${KEY_FILE}"
chmod 644 "${CERT_FILE}"
# The API container reads these as the app user.
chown "${APP_UID:-10001}:${APP_GID:-10001}" "${KEY_FILE}" "${CERT_FILE}" 2>/dev/null \
    || warn "could not chown the certificate files; ensure uid ${APP_UID:-10001} can read them"

ok "wrote ${CERT_FILE}"
ok "wrote ${KEY_FILE}"
warn "This certificate is SELF-SIGNED. Browsers and API clients will refuse or"
warn "warn about it. Replace it with a certificate from your own CA before"
warn "this deployment handles production investigation material."
