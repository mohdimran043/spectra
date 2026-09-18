"""Make the pip-installed NVIDIA runtime libraries loadable by native extensions.

PyTorch ships cuDNN and cuBLAS as wheels under ``site-packages/nvidia/`` and
finds them through its own RPATH.  Other native extensions - notably
CTranslate2, which powers faster-whisper - call ``dlopen("libcudnn_ops.so.9")``
and rely on the system loader, which does not look there.  The result is a
**native abort**, not a Python exception:

    Unable to load any of {libcudnn_ops.so.9.1.0, libcudnn_ops.so.9.1, ...}
    Invalid handle. Cannot load symbol cudnnCreateTensorDescriptor

That kills the whole process, so it has to be prevented rather than caught.
Pre-loading the libraries with ``RTLD_GLOBAL`` puts their symbols in the global
namespace, and the later ``dlopen`` resolves against them.

``probe()`` is also what lets the model registry *decide*: if the CUDA libraries
cannot be made loadable, the CUDA Whisper candidate is reported unavailable and
the CPU candidate is selected instead - a slower transcription rather than a
dead worker.
"""

from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from spectra_config.logging import get_logger

log = get_logger(__name__)

# Load order matters: the dependency graph is ops -> {graph, engines}, and
# cuDNN's own loader expects its siblings to already be resolvable.
CUDNN_LIBRARIES: tuple[str, ...] = (
    "libcudnn_graph.so.9",
    "libcudnn_engines_precompiled.so.9",
    "libcudnn_engines_runtime_compiled.so.9",
    "libcudnn_heuristic.so.9",
    "libcudnn_ops.so.9",
    "libcudnn_cnn.so.9",
    "libcudnn_adv.so.9",
    "libcudnn.so.9",
)
CUBLAS_LIBRARIES: tuple[str, ...] = ("libcublasLt.so.12", "libcublas.so.12")
NVIDIA_PACKAGES: tuple[str, ...] = ("cudnn", "cublas")


@dataclass(frozen=True)
class CudaLibraryStatus:
    """Whether the native CUDA libraries can be loaded, and why not if they cannot."""

    cudnn_ready: bool
    cublas_ready: bool
    search_paths: tuple[str, ...] = ()
    detail: str = ""

    @property
    def ready(self) -> bool:
        return self.cudnn_ready and self.cublas_ready


def library_directories() -> tuple[Path, ...]:
    """Every ``site-packages/nvidia/<pkg>/lib`` directory on this interpreter."""
    found: list[Path] = []
    for entry in sys.path:
        if not entry:
            continue
        for package in NVIDIA_PACKAGES:
            candidate = Path(entry) / "nvidia" / package / "lib"
            if candidate.is_dir() and candidate not in found:
                found.append(candidate)
    return tuple(found)


def _preload(directories: tuple[Path, ...], names: tuple[str, ...]) -> tuple[bool, str]:
    """dlopen each library with RTLD_GLOBAL so later loads resolve against it."""
    if not directories:
        return False, "no site-packages/nvidia/*/lib directory was found"

    missing: list[str] = []
    failures: list[str] = []
    for name in names:
        path = next((d / name for d in directories if (d / name).exists()), None)
        if path is None:
            missing.append(name)
            continue
        try:
            ctypes.CDLL(str(path), mode=ctypes.RTLD_GLOBAL)
        except OSError as exc:
            failures.append(f"{name}: {exc}")

    # Only the primary libraries must be present; the optional engine plugins
    # are loaded opportunistically because not every wheel version ships them.
    required = {"libcudnn_ops.so.9", "libcudnn.so.9", "libcublas.so.12", "libcublasLt.so.12"}
    blocking = [n for n in missing if n in required]
    if blocking:
        return False, f"missing: {', '.join(blocking)}"
    if failures:
        return False, "; ".join(failures)
    return True, "preloaded"


@lru_cache(maxsize=1)
def ensure_loaded() -> CudaLibraryStatus:
    """Preload cuDNN and cuBLAS once per process.  Never raises."""
    directories = library_directories()
    try:
        cudnn_ok, cudnn_detail = _preload(directories, CUDNN_LIBRARIES)
        cublas_ok, cublas_detail = _preload(directories, CUBLAS_LIBRARIES)
    except Exception as exc:  # pragma: no cover - defensive; this must never raise
        log.warning("cuda_libs.preload_failed", error=str(exc))
        return CudaLibraryStatus(False, False, tuple(str(d) for d in directories), str(exc))

    status = CudaLibraryStatus(
        cudnn_ready=cudnn_ok,
        cublas_ready=cublas_ok,
        search_paths=tuple(str(d) for d in directories),
        detail=f"cudnn: {cudnn_detail}; cublas: {cublas_detail}",
    )
    if status.ready:
        log.info("cuda_libs.ready", paths=len(directories))
    else:
        log.warning("cuda_libs.unavailable", detail=status.detail)
    return status


def probe() -> CudaLibraryStatus:
    """Public check used by providers before they select a CUDA candidate."""
    return ensure_loaded()


def ld_library_path() -> str:
    """The value LD_LIBRARY_PATH would need, for container images and docs."""
    directories = [str(d) for d in library_directories()]
    existing = os.environ.get("LD_LIBRARY_PATH", "")
    if existing:
        directories.append(existing)
    return ":".join(directories)
