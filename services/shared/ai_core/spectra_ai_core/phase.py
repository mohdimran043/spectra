"""Execution phase - the architectural law, enforced rather than documented.

SPECTRA's central rule is that expensive media processing happens **once, at
ingestion**, and never at query time.  That rule is what makes the TB-scale
claim credible: a query costs index lookups, not OCR.

A comment cannot enforce that.  This module can: model capabilities are tagged
by the phase they belong to, the active phase is tracked in a context variable,
and asking the gateway to OCR an image or transcribe audio while serving a query
raises instead of quietly doing it.

    async with ingestion_phase():
        await gateway.ocr(image_bytes)        # fine - this is the write path

    async with query_phase():
        await gateway.ocr(image_bytes)        # PhaseViolation
        await gateway.embed_texts([query])    # fine - embedding a query is cheap

The phase defaults to UNSET, which permits everything, so library use and tests
are unaffected until a caller opts in.
"""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from enum import Enum

from spectra_config.logging import get_logger

log = get_logger(__name__)


class ExecutionPhase(str, Enum):
    """Which pipeline the current task belongs to."""

    UNSET = "unset"
    #: Pipeline A - writes indexes.  May use every capability.
    INGESTION = "ingestion"
    #: Pipeline B - reads indexes.  May not run per-object media processing.
    QUERY = "query"


_phase: ContextVar[ExecutionPhase] = ContextVar("execution_phase", default=ExecutionPhase.UNSET)

# Capabilities that process a raw object and must therefore run exactly once,
# during ingestion.  Running any of these per query is the failure mode the
# architecture exists to prevent.
INGESTION_ONLY: frozenset[str] = frozenset(
    {
        "ocr",              # reading text off an image
        "transcribe",       # speech recognition over an audio stream
        "describe_image",   # vision captioning of an image or keyframe
        "embed_images",     # embedding raw image bytes
    }
)

# Capabilities that are legitimately cheap per call and belong to both pipelines.
QUERY_SAFE: frozenset[str] = frozenset(
    {
        "embed_texts",                 # embedding one short query string
        "embed_text_for_image_space",  # text -> multimodal space, for text->image search
        "rerank",                      # cross-encoder over the top-K only
        "generate",                    # planning and synthesis
    }
)


class PhaseViolation(RuntimeError):
    """Raised when the query path attempts ingestion-only work."""

    def __init__(self, capability: str) -> None:
        super().__init__(
            f"'{capability}' is an ingestion-time capability and must not run while serving a "
            "query: it processes a raw object, so its cost grows with corpus size. "
            "Index the result during ingestion and retrieve it instead. "
            "(See docs/architecture.md, 'Two pipelines'.)"
        )
        self.capability = capability


def current_phase() -> ExecutionPhase:
    return _phase.get()


def guard(capability: str) -> None:
    """Refuse an ingestion-only capability while the query path is active."""
    if capability in INGESTION_ONLY and _phase.get() is ExecutionPhase.QUERY:
        log.error("phase.violation", capability=capability, phase=ExecutionPhase.QUERY.value)
        raise PhaseViolation(capability)


@contextmanager
def phase(value: ExecutionPhase):
    """Set the execution phase for the duration of a synchronous block."""
    token = _phase.set(value)
    try:
        yield value
    finally:
        _phase.reset(token)


@asynccontextmanager
async def ingestion_phase():
    """Mark the enclosed work as Pipeline A - every capability is permitted."""
    token = _phase.set(ExecutionPhase.INGESTION)
    try:
        yield ExecutionPhase.INGESTION
    finally:
        _phase.reset(token)


@asynccontextmanager
async def query_phase():
    """Mark the enclosed work as Pipeline B - ingestion-only capabilities are refused."""
    token = _phase.set(ExecutionPhase.QUERY)
    try:
        yield ExecutionPhase.QUERY
    finally:
        _phase.reset(token)
