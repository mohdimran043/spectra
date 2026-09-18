#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Report what the model layer is doing: registered models, load state, VRAM.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

usage() {
    cat <<'USAGE_EOF'
model-health.sh - model registry, load state and VRAM

SYNOPSIS
    ./scripts/model-health.sh [--url http://host:8000]
    make model-health

WHAT IT DOES
    Queries the running API for model health, then falls back to what can be
    told without it: the configured model set, the weights present in MODEL_DIR,
    and current GPU memory.

OPTIONS
    --url URL    API base URL (default: http://127.0.0.1:${API_PUBLISHED_PORT:-8000})
    -h, --help   this text
USAGE_EOF
}

for arg in "$@"; do
    case "${arg}" in -h|--help) usage; exit 0 ;; esac
done

API_URL=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --url) API_URL="${2:?--url needs a value}"; shift 2 ;;
        *) printf 'unknown argument: %s (try --help)\n' "$1" >&2; exit 1 ;;
    esac
done

# Pull a few values out of .env without sourcing it.
env_value() {
    local key="$1" default="${2:-}"
    local found=""
    [[ -f "${REPO_ROOT}/.env" ]] && found="$(sed -n "s/^[[:space:]]*${key}=//p" "${REPO_ROOT}/.env" | tail -n 1)"
    printf '%s' "${found:-${default}}"
}

API_URL="${API_URL:-http://127.0.0.1:$(env_value API_PUBLISHED_PORT "$(env_value API_PORT 8000)")}"

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

step "API model health  (${API_URL})"
if command -v curl >/dev/null 2>&1 && curl -fsS --max-time 10 "${API_URL}/api/health" >/tmp/spectra-health.$$ 2>/dev/null; then
    if command -v python3 >/dev/null 2>&1; then
        python3 -m json.tool /tmp/spectra-health.$$ 2>/dev/null | sed 's/^/  /' || sed 's/^/  /' /tmp/spectra-health.$$
    else
        sed 's/^/  /' /tmp/spectra-health.$$
    fi
    curl -fsS --max-time 10 "${API_URL}/api/models" 2>/dev/null \
        | { command -v python3 >/dev/null 2>&1 && python3 -m json.tool 2>/dev/null || cat; } \
        | sed 's/^/  /' || printf '  (no /api/models endpoint)\n'
    rm -f /tmp/spectra-health.$$
else
    printf '  API not reachable at %s\n' "${API_URL}"
    printf '  Start it with: make up      or   uvicorn spectra_api.main:app --port 8000\n'
    rm -f /tmp/spectra-health.$$ 2>/dev/null || true
fi

step "Configured models"
for key in MODEL_PROFILE MODEL_RUNTIME GPU_VRAM_BUDGET_MB FAST_BRAIN_MODEL DEEP_BRAIN_MODEL \
           VISION_MODEL EMBEDDING_MODEL MM_EMBEDDING_MODEL RERANKER_MODEL WHISPER_MODEL OCR_ENGINE; do
    printf '  %-22s %s\n' "${key}" "$(env_value "${key}" '(default)')"
done

step "Weights on disk"
MODEL_DIR="$(env_value MODEL_DIR "${REPO_ROOT}/models")"
if [[ -d "${MODEL_DIR}" ]]; then
    printf '  %s (%s)\n' "${MODEL_DIR}" "$(du -sh "${MODEL_DIR}" 2>/dev/null | cut -f1)"
    find "${MODEL_DIR}" -maxdepth 2 \( -name '*.gguf' -o -name '*.safetensors' -o -name '*.bin' \) \
        -printf '  %-58p %s bytes\n' 2>/dev/null | head -n 20 || true
    [[ -z "$(find "${MODEL_DIR}" -maxdepth 2 -type f 2>/dev/null | head -n 1)" ]] \
        && printf '  (empty - models are downloaded or mounted on first use)\n'
else
    printf '  %s does not exist yet\n' "${MODEL_DIR}"
fi

step "GPU"
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu \
               --format=csv,noheader | sed 's/^/  /'
    printf '\n  processes holding VRAM:\n'
    nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader 2>/dev/null \
        | sed 's/^/    /' || printf '    none\n'
else
    printf '  no GPU visible - run ./scripts/gpu-check.sh for the reason\n'
fi
