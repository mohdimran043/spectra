#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Lint and format checks for the Python monorepo (and the apps when present).
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

usage() {
    cat <<'USAGE_EOF'
lint.sh - ruff + black checks, and the frontend linters when they exist

SYNOPSIS
    ./scripts/lint.sh [--fix] [--python-only]
    make lint        (check)      make format   (fix)

OPTIONS
    --fix           apply fixes instead of only reporting (ruff --fix, black)
    --python-only   skip the Next.js apps
    -h, --help      this text

EXIT STATUS
    non-zero if anything is unformatted or fails a lint rule
USAGE_EOF
}

for arg in "$@"; do
    case "${arg}" in -h|--help) usage; exit 0 ;; esac
done

FIX=0
PYTHON_ONLY=0
for arg in "$@"; do
    case "${arg}" in
        --fix)         FIX=1 ;;
        --python-only) PYTHON_ONLY=1 ;;
        *) printf 'unknown argument: %s (try --help)\n' "${arg}" >&2; exit 1 ;;
    esac
done

BIN="${REPO_ROOT}/.venv/bin"
[[ -x "${BIN}/ruff" ]] || BIN=""
RUFF="${BIN:+${BIN}/}ruff"
BLACK="${BIN:+${BIN}/}black"

step()   { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
STATUS=0

step "ruff"
if command -v "${RUFF}" >/dev/null 2>&1; then
    if [[ ${FIX} -eq 1 ]]; then
        "${RUFF}" check --fix "${REPO_ROOT}" || STATUS=1
    else
        "${RUFF}" check "${REPO_ROOT}" || STATUS=1
    fi
else
    printf '  ruff not installed - run ./scripts/bootstrap.sh\n'
    STATUS=1
fi

step "black"
if command -v "${BLACK}" >/dev/null 2>&1; then
    if [[ ${FIX} -eq 1 ]]; then
        "${BLACK}" "${REPO_ROOT}" || STATUS=1
    else
        "${BLACK}" --check "${REPO_ROOT}" || STATUS=1
    fi
else
    printf '  black not installed - run ./scripts/bootstrap.sh\n'
    STATUS=1
fi

step "shell scripts"
if command -v shellcheck >/dev/null 2>&1; then
    # shellcheck disable=SC2046
    shellcheck -x $(find "${REPO_ROOT}/scripts" "${REPO_ROOT}/deploy/scripts" -name '*.sh') || STATUS=1
else
    printf '  shellcheck not installed; falling back to bash -n\n'
    while IFS= read -r script; do
        bash -n "${script}" || { printf '  syntax error: %s\n' "${script}"; STATUS=1; }
    done < <(find "${REPO_ROOT}/scripts" "${REPO_ROOT}/deploy/scripts" -name '*.sh')
    printf '  all shell scripts parse\n'
fi

if [[ ${PYTHON_ONLY} -eq 0 ]]; then
    for app in frontend mock-enterprise; do
        dir="${REPO_ROOT}/apps/${app}"
        [[ -f "${dir}/package.json" ]] || continue
        step "${app}"
        if [[ -d "${dir}/node_modules" ]]; then
            ( cd "${dir}" && npm run --if-present lint ) || STATUS=1
        else
            printf '  node_modules missing; run npm install in %s\n' "${dir}"
        fi
    done
fi

step "Summary"
if [[ ${STATUS} -eq 0 ]]; then
    printf '  clean\n'
else
    printf '  issues found\n'
fi
exit ${STATUS}
