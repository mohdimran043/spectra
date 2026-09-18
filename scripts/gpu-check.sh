#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Report GPU readiness for SPECTRA, and name the failure precisely when the
# NVIDIA driver and the userspace libraries disagree.
# ---------------------------------------------------------------------------
set -euo pipefail

usage() {
    cat <<'USAGE_EOF'
gpu-check.sh - is this host ready to run SPECTRA models on the GPU?

SYNOPSIS
    ./scripts/gpu-check.sh
    make gpu-check

CHECKS
    driver      nvidia-smi, driver version, CUDA runtime version, VRAM
    mismatch    the classic "Driver/library version mismatch" after an in-place
                driver upgrade, with the exact remedy
    docker      whether the NVIDIA Container Toolkit is registered with Docker
    torch       whether the installed PyTorch can actually see the device

EXIT STATUS
    0  a usable GPU was found
    1  no usable GPU (SPECTRA still runs: set MODEL_PROFILE=cpu, GPU_ENABLED=0)
USAGE_EOF
}

for arg in "$@"; do
    case "${arg}" in -h|--help) usage; exit 0 ;; esac
done

C_R=$'\033[31m'; C_G=$'\033[32m'; C_Y=$'\033[33m'; C_B=$'\033[1m'; C_0=$'\033[0m'
step() { printf '\n%s==> %s%s\n' "${C_B}" "$*" "${C_0}"; }
good() { printf '  %s[ok]%s   %s\n'   "${C_G}" "${C_0}" "$*"; }
bad()  { printf '  %s[fail]%s %s\n'   "${C_R}" "${C_0}" "$*"; }
warn() { printf '  %s[warn]%s %s\n'   "${C_Y}" "${C_0}" "$*"; }

STATUS=0

step "NVIDIA driver"
if ! command -v nvidia-smi >/dev/null 2>&1; then
    bad "nvidia-smi not found - no NVIDIA driver on this host"
    warn "SPECTRA runs CPU-only: set MODEL_PROFILE=cpu and GPU_ENABLED=0"
    STATUS=1
else
    if smi_output="$(nvidia-smi 2>&1)"; then
        driver="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n 1)"
        name="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n 1)"
        total="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader 2>/dev/null | head -n 1)"
        used="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader 2>/dev/null | head -n 1)"
        good "${name:-unknown GPU}"
        good "driver ${driver:-unknown}, VRAM ${used:-?} used of ${total:-?}"
    else
        bad "nvidia-smi failed:"
        printf '%s\n' "${smi_output}" | sed 's/^/         /'
        if printf '%s' "${smi_output}" | grep -qi 'Driver/library version mismatch'; then
            printf '\n  %sDRIVER / LIBRARY VERSION MISMATCH%s\n' "${C_B}" "${C_0}"
            printf '  The kernel module currently loaded is a different version from the\n'
            printf '  userspace NVIDIA libraries - almost always an in-place driver upgrade\n'
            printf '  that has not been followed by a reboot.\n\n'
            printf '  Loaded kernel module: %s\n' "$(cat /proc/driver/nvidia/version 2>/dev/null | head -n 1 || echo 'unreadable')"
            printf '  Installed libraries : %s\n' "$(ls /usr/lib/x86_64-linux-gnu/libnvidia-ml.so.* 2>/dev/null | head -n 1 || echo 'not found')"
            printf '\n  Fix, in order of preference:\n'
            printf '    1. sudo reboot                       (always works)\n'
            printf '    2. stop everything using the GPU, then:\n'
            printf '       sudo rmmod nvidia_uvm nvidia_drm nvidia_modeset nvidia\n'
            printf '       sudo modprobe nvidia\n'
            printf '    3. reinstall the matching driver package if the mismatch persists\n\n'
        fi
        STATUS=1
    fi
fi

step "CUDA runtime"
if command -v nvcc >/dev/null 2>&1; then
    good "nvcc $(nvcc --version | sed -n 's/.*release \([0-9.]*\).*/\1/p')"
elif command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
    cuda="$(nvidia-smi | sed -n 's/.*CUDA Version: *\([0-9.]*\).*/\1/p' | head -n 1)"
    good "driver supports CUDA ${cuda:-unknown} (nvcc not installed; not needed for prebuilt wheels)"
else
    warn "no CUDA toolchain detected"
fi

step "Docker GPU runtime"
if command -v docker >/dev/null 2>&1; then
    if docker info 2>/dev/null | grep -qi 'nvidia'; then
        good "the nvidia runtime is registered with Docker"
        printf '         start the stack with GPU: make up GPU=1\n'
    else
        warn "the NVIDIA Container Toolkit is not registered with Docker"
        printf '         containers will NOT see the GPU. Install nvidia-container-toolkit,\n'
        printf '         then: sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker\n'
        printf '         Until then keep GPU_ENABLED=0 in .env, or `up` fails with:\n'
        printf '           could not select device driver "nvidia" with capabilities: [[gpu]]\n'
    fi
else
    warn "docker not installed; skipping the container runtime check"
fi

step "PyTorch"
PY="${PYTHON:-python3}"
[[ -x "$(dirname "$0")/../.venv/bin/python" ]] && PY="$(cd "$(dirname "$0")/.." && pwd)/.venv/bin/python"
"${PY}" - <<'PY' 2>/dev/null || printf '  [warn] torch is not installed (install the [ml] extra for GPU inference)\n'
try:
    import torch
except ModuleNotFoundError:
    raise SystemExit(1)
if torch.cuda.is_available():
    idx = torch.cuda.current_device()
    total = torch.cuda.get_device_properties(idx).total_memory / (1024 ** 3)
    print(f"  [ok]   torch {torch.__version__} sees {torch.cuda.get_device_name(idx)} ({total:.1f} GiB)")
else:
    print(f"  [warn] torch {torch.__version__} is installed but reports no CUDA device")
    print(f"         built for CUDA {getattr(torch.version, 'cuda', None)}")
PY

step "Summary"
if [[ ${STATUS} -eq 0 ]]; then
    printf '  GPU looks usable. Recommended: MODEL_PROFILE=rtx4090, GPU_ENABLED=1\n'
else
    printf '  No usable GPU. SPECTRA still runs: MODEL_PROFILE=cpu, GPU_ENABLED=0,\n'
    printf '  and the Brain reports degraded mode rather than failing.\n'
fi
exit ${STATUS}
