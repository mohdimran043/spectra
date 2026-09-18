"""GPU detection and OOM classification.

Detection is a ladder - NVML, then ``torch.cuda``, then the ``nvidia-smi``
binary - and it is *total*: every probe failure is captured as text and folded
into :attr:`GPUStatus.detail`.  A machine with a driver/library version
mismatch reports ``available=False`` with the mismatch quoted, never an
exception, because the whole platform is required to degrade to CPU cleanly.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

from spectra_config import Settings
from spectra_config.logging import get_logger
from spectra_schemas import GPUStatus

log = get_logger(__name__)

NVIDIA_SMI = "nvidia-smi"
SMI_TIMEOUT_SECONDS = 10
SMI_QUERY = "name,driver_version,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu"
SMI_FORMAT = "csv,noheader,nounits"
SMI_FIELD_COUNT = 7
BYTES_PER_MB = 1024 * 1024

# Substrings that identify an out-of-memory condition across CUDA, torch and
# the llama.cpp / ggml allocators.  Matched case-insensitively against str(exc).
OOM_SIGNATURES: tuple[str, ...] = (
    "out of memory",
    "outofmemory",
    "cuda_error_out_of_memory",
    "cublas_status_alloc_failed",
    "cudnn_status_alloc_failed",
    "failed to allocate",
    "unable to allocate",
    "ggml_new_object",
    "ggml_backend_buffer",
    "llama_kv_cache_init",
    "failed to allocate buffer",
    "insufficient memory",
    "not enough memory",
    "alloc failed",
)


def _probe_nvml() -> tuple[GPUStatus | None, str]:
    """Preferred probe: pynvml / nvidia-ml-py gives driver version and utilisation."""
    try:
        import pynvml  # noqa: PLC0415 - optional dependency, imported lazily on purpose
    except Exception as exc:
        return None, f"pynvml unavailable ({exc})"
    try:
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
        status = GPUStatus(
            available=True,
            name=_decode(pynvml.nvmlDeviceGetName(handle)),
            driver_version=_decode(pynvml.nvmlSystemGetDriverVersion()),
            total_mb=memory.total / BYTES_PER_MB,
            used_mb=memory.used / BYTES_PER_MB,
            free_mb=memory.free / BYTES_PER_MB,
            utilisation_pct=float(pynvml.nvmlDeviceGetUtilizationRates(handle).gpu),
            temperature_c=float(pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)),
            detail="nvml",
        )
        return status, ""
    except Exception as exc:
        return None, f"nvml probe failed ({exc})"
    finally:
        _shutdown_nvml()


def _shutdown_nvml() -> None:
    try:
        import pynvml

        pynvml.nvmlShutdown()
    except Exception:  # noqa: S110 - shutdown of a probe must never surface
        pass


def _decode(value: Any) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def _probe_torch() -> tuple[GPUStatus | None, str]:
    """Second probe: torch reports False (rather than raising) on a broken driver."""
    try:
        import torch  # noqa: PLC0415 - optional heavy dependency
    except Exception as exc:
        return None, f"torch unavailable ({exc})"
    try:
        if not torch.cuda.is_available():
            return None, "torch.cuda.is_available() is False"
        index = torch.cuda.current_device()
        free_bytes, total_bytes = torch.cuda.mem_get_info(index)
        properties = torch.cuda.get_device_properties(index)
        return (
            GPUStatus(
                available=True,
                name=properties.name,
                driver_version=getattr(torch.version, "cuda", None),
                total_mb=total_bytes / BYTES_PER_MB,
                used_mb=(total_bytes - free_bytes) / BYTES_PER_MB,
                free_mb=free_bytes / BYTES_PER_MB,
                detail="torch.cuda",
            ),
            "",
        )
    except Exception as exc:
        return None, f"torch.cuda probe failed ({exc})"


def _probe_smi() -> tuple[GPUStatus | None, str]:
    """Last probe.  Also the one that yields a human-readable driver-mismatch message."""
    binary = shutil.which(NVIDIA_SMI)
    if binary is None:
        return None, f"{NVIDIA_SMI} not on PATH"
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [binary, f"--query-gpu={SMI_QUERY}", f"--format={SMI_FORMAT}"],
            capture_output=True,
            text=True,
            timeout=SMI_TIMEOUT_SECONDS,
            check=False,
        )
    except Exception as exc:
        return None, f"{NVIDIA_SMI} failed to run ({exc})"
    # nvidia-smi writes driver errors to stdout and exits non-zero.
    message = (completed.stdout.strip() or completed.stderr.strip()).splitlines()
    if completed.returncode != 0:
        return None, f"{NVIDIA_SMI} exited {completed.returncode}: {' | '.join(message) or 'no output'}"
    return _parse_smi_row(message)


def _parse_smi_row(lines: list[str]) -> tuple[GPUStatus | None, str]:
    if not lines:
        return None, f"{NVIDIA_SMI} returned no rows"
    fields = [field.strip() for field in lines[0].split(",")]
    if len(fields) < SMI_FIELD_COUNT:
        return None, f"{NVIDIA_SMI} output not parseable: {lines[0]!r}"
    try:
        total, used, free = (float(fields[2]), float(fields[3]), float(fields[4]))
        utilisation, temperature = _optional_float(fields[5]), _optional_float(fields[6])
    except ValueError as exc:
        return None, f"{NVIDIA_SMI} numeric field not parseable ({exc})"
    return (
        GPUStatus(
            available=True,
            name=fields[0],
            driver_version=fields[1],
            total_mb=total,
            used_mb=used,
            free_mb=free,
            utilisation_pct=utilisation,
            temperature_c=temperature,
            detail=NVIDIA_SMI,
        ),
        "",
    )


def _optional_float(value: str) -> float | None:
    return None if value in {"", "N/A", "[N/A]"} else float(value)


def detect_gpu(settings: Settings | None = None) -> GPUStatus:
    """Return GPU telemetry.  Never raises; ``detail`` explains any unavailability."""
    budget = float(settings.gpu_vram_budget_mb) if settings else 0.0
    reasons: list[str] = []
    for probe in (_probe_nvml, _probe_torch, _probe_smi):
        status, reason = probe()
        if status is not None:
            return status.model_copy(update={"budget_mb": min(budget, status.total_mb) or budget})
        reasons.append(reason)
    detail = "; ".join(reasons)
    log.info("gpu.unavailable", detail=detail)
    return GPUStatus(available=False, budget_mb=0.0, detail=detail)


def gpu_memory_snapshot() -> dict[str, float]:
    """Live VRAM figures in MB.  All zeros when no GPU is usable."""
    status = detect_gpu()
    if not status.available:
        return {"total_mb": 0.0, "used_mb": 0.0, "free_mb": 0.0}
    return {"total_mb": status.total_mb, "used_mb": status.used_mb, "free_mb": status.free_mb}


def is_oom_error(exc: BaseException | None) -> bool:
    """True for CUDA OOM, ``torch.cuda.OutOfMemoryError`` and ggml/llama.cpp alloc failures."""
    if exc is None:
        return False
    if isinstance(exc, MemoryError):
        return True
    if _is_torch_oom(exc):
        return True
    haystack = f"{type(exc).__name__} {exc}".lower()
    if any(signature in haystack for signature in OOM_SIGNATURES):
        return True
    cause = exc.__cause__ or exc.__context__
    return is_oom_error(cause) if cause is not None and cause is not exc else False


def _is_torch_oom(exc: BaseException) -> bool:
    try:
        import torch

        return isinstance(exc, torch.cuda.OutOfMemoryError)
    except Exception:
        return False
