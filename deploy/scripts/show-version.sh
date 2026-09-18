#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Print bundle, configured and deployed versions side by side.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

usage() {
    cat <<'USAGE_EOF'
show-version.sh - what version is in the bundle, in .env, and actually running

SYNOPSIS
    ./scripts/show-version.sh

OUTPUT
    bundle    the VERSION file shipped in this bundle
    .env      APP_VERSION the stack would start with
    deployed  $APP_ROOT/.deployed_version, written by the last successful deploy

    A mismatch between .env and deployed means a deploy was started and did not
    finish, or someone edited .env without redeploying.

OPTIONS
    -h, --help   this text
USAGE_EOF
}

handle_help "$@"

bundle_version="(none)"
[[ -f "${DEPLOY_DIR}/VERSION" ]] && bundle_version="$(tr -d '[:space:]' < "${DEPLOY_DIR}/VERSION")"

env_version="(no .env)"
app_root_display="(unknown)"
if [[ -f "${ENV_FILE}" ]]; then
    load_env
    env_version="${APP_VERSION}"
    app_root_display="${APP_ROOT}"
fi

deployed="(never deployed)"
if [[ -n "${APP_ROOT:-}" && -f "$(version_file)" ]]; then
    deployed="$(deployed_version)"
fi

printf '%-10s %s\n' "app"      "${APP_SLUG}"
printf '%-10s %s\n' "bundle"   "${bundle_version}"
printf '%-10s %s\n' ".env"     "${env_version}"
printf '%-10s %s\n' "deployed" "${deployed}"
printf '%-10s %s\n' "app_root" "${app_root_display}"

if [[ "${env_version}" != "(no .env)" && "${deployed}" != "(never deployed)" && "${env_version}" != "${deployed}" ]]; then
    warn ".env (${env_version}) and the deployed version (${deployed}) disagree - run ./scripts/deploy.sh"
fi
