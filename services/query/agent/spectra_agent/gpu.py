"""Single-GPU scheduling for the Brain.

SPECTRA targets one 24 GB card.  Every tool that touches a GPU model is awaited
through this module-level semaphore, so vision, multimodal embedding and
reranking never contend for VRAM even when the Brain fans retrieval out with
``asyncio.gather``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import TypeVar

from spectra_config.logging import get_logger

log = get_logger(__name__)

T = TypeVar("T")

# One card, one in-flight GPU job.
_GPU_SEMAPHORE = asyncio.Semaphore(1)


class GpuScheduler:
    """Serialises GPU-heavy work behind a shared semaphore."""

    @staticmethod
    @asynccontextmanager
    async def slot(label: str = "") -> AsyncIterator[None]:
        waiting = _GPU_SEMAPHORE.locked()
        if waiting:
            log.debug("gpu.queued", label=label)
        await _GPU_SEMAPHORE.acquire()
        try:
            yield
        finally:
            _GPU_SEMAPHORE.release()

    @staticmethod
    async def run(factory: Callable[[], Awaitable[T]], *, label: str = "") -> T:
        """Await ``factory()`` while holding the single GPU slot."""
        async with GpuScheduler.slot(label):
            return await factory()

    @staticmethod
    def busy() -> bool:
        return _GPU_SEMAPHORE.locked()
