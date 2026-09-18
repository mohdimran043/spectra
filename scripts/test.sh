#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Run the SPECTRA test suite with coverage.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

usage() {
    cat <<'USAGE_EOF'
test.sh - pytest with coverage

SYNOPSIS
    ./scripts/test.sh [--unit|--integration|--e2e|--all] [--no-cov] [pytest args...]
    make test

MARKERS (declared in pyproject.toml)
    integration   needs external infrastructure (make up first)
    e2e           full acceptance scenario
    slow          long running

    The default run excludes integration and e2e so it stays fast and needs no
    Docker.

OPTIONS
    --unit         unit tests only (the default)
    --integration  integration tests only
    --e2e          end-to-end tests only
    --all          everything, markers included
    --no-cov       skip coverage measurement
    -h, --help     this text

COVERAGE
    The project target is 80%.  Coverage is reported as a terminal summary plus
    htmlcov/ for browsing.
USAGE_EOF
}

for arg in "$@"; do
    case "${arg}" in -h|--help) usage; exit 0 ;; esac
done

SELECTION="unit"
COVERAGE=1
PYTEST_ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --unit)        SELECTION="unit"; shift ;;
        --integration) SELECTION="integration"; shift ;;
        --e2e)         SELECTION="e2e"; shift ;;
        --all)         SELECTION="all"; shift ;;
        --no-cov)      COVERAGE=0; shift ;;
        *)             PYTEST_ARGS+=("$1"); shift ;;
    esac
done

PYTEST="${REPO_ROOT}/.venv/bin/pytest"
[[ -x "${PYTEST}" ]] || PYTEST="pytest"
command -v "${PYTEST}" >/dev/null 2>&1 || { printf 'pytest not found - run ./scripts/bootstrap.sh\n' >&2; exit 1; }

case "${SELECTION}" in
    unit)        PYTEST_ARGS+=(-m "not integration and not e2e") ;;
    integration) PYTEST_ARGS+=(-m "integration") ;;
    e2e)         PYTEST_ARGS+=(-m "e2e") ;;
    all)         ;;
esac

if [[ ${COVERAGE} -eq 1 ]]; then
    PYTEST_ARGS+=(
        --cov=packages --cov=services --cov=evaluation
        --cov-report=term-missing --cov-report=html
    )
fi

printf '\033[1m==> pytest (%s)\033[0m\n' "${SELECTION}"
cd "${REPO_ROOT}"
exec "${PYTEST}" "${PYTEST_ARGS[@]}"
