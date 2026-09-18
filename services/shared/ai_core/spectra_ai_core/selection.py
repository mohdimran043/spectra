"""Candidate selection: which implementation of a role actually runs here, and why.

Every rejection is recorded on the candidate itself, so ``status()`` can explain
the choice to an operator instead of silently degrading.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field

from spectra_config import ModelRuntime, Settings
from spectra_config.logging import get_logger
from spectra_schemas import GPUStatus, ModelCandidate, ModelRole

from .interfaces import BaseProvider
from .providers import OcrResolver, UnsupportedCandidateError, build_provider
from .registry import ProfileSpec, RoleSpec

log = get_logger(__name__)

PROBE_CONCURRENCY = 8
PROBE_TIMEOUT_SECONDS = 10.0
DETERMINISTIC_RUNTIME = "deterministic"
CUDA = "cuda"
CPU = "cpu"
REMOTE = "remote"
AUTO = "auto"
NO_CANDIDATE_REASON = "no candidate is usable on this machine"
ROLE_DISABLED_REASON = "role is disabled in models.yaml"


@dataclass(frozen=True)
class SelectionContext:
    """Everything that constrains a choice: hardware, profile and configuration."""

    settings: Settings
    profile: ProfileSpec
    gpu: GPUStatus
    ocr_resolver: OcrResolver | None = None


@dataclass(frozen=True)
class Selection:
    """The outcome for one role."""

    role: ModelRole
    provider: BaseProvider | None
    candidate: ModelCandidate | None
    device: str
    candidates: tuple[ModelCandidate, ...] = field(default_factory=tuple)
    reason: str = ""

    @property
    def is_degraded(self) -> bool:
        return self.candidate is not None and self.candidate.runtime == DETERMINISTIC_RUNTIME


def resolve_device(requested: str, profile: ProfileSpec, gpu_available: bool) -> str | None:
    """Map a candidate's declared device onto this machine.  ``None`` means 'cannot run here'."""
    if requested == REMOTE:
        return REMOTE
    if requested == CUDA:
        return CUDA if gpu_available else None
    if requested == CPU:
        return CPU
    return CUDA if gpu_available and profile.prefer_device == CUDA else CPU


def _runtime_rejection(candidate: ModelCandidate, settings: Settings) -> str:
    """Honour a pinned MODEL_RUNTIME, but never disarm the deterministic safety net."""
    pinned = settings.model_runtime
    if pinned is ModelRuntime.AUTO or candidate.runtime == DETERMINISTIC_RUNTIME:
        return ""
    return "" if candidate.runtime == pinned.value else f"runtime pinned to {pinned.value}"


def _static_rejection(
    candidate: ModelCandidate, device: str | None, context: SelectionContext
) -> str:
    if device is None:
        return f"requires cuda but no GPU is usable: {context.gpu.detail or 'unknown'}"
    if device == CUDA and candidate.vram_mb > context.profile.vram_budget_mb:
        return (
            f"needs {candidate.vram_mb} MB VRAM, profile "
            f"{context.profile.name} budget is {context.profile.vram_budget_mb} MB"
        )
    return _runtime_rejection(candidate, context.settings)


async def _probe(
    candidate: ModelCandidate,
    role: ModelRole,
    context: SelectionContext,
    dimension: int | None,
    semaphore: asyncio.Semaphore,
) -> tuple[ModelCandidate, BaseProvider | None, str]:
    """Annotate one candidate with its availability.  Never raises."""
    device = resolve_device(candidate.device, context.profile, context.gpu.available)
    rejection = _static_rejection(candidate, device, context)
    if rejection:
        return candidate.model_copy(update={"available": False, "unavailable_reason": rejection}), None, ""
    try:
        provider = build_provider(
            candidate=candidate,
            role=role,
            settings=context.settings,
            device=device or CPU,
            dimension=dimension,
            ocr_resolver=context.ocr_resolver,
        )
    except UnsupportedCandidateError as exc:
        return candidate.model_copy(update={"available": False, "unavailable_reason": str(exc)}), None, ""
    ok, reason = await _safe_available(provider, semaphore)
    annotated = candidate.model_copy(update={"available": ok, "unavailable_reason": None if ok else reason})
    return annotated, (provider if ok else None), device or CPU


async def _safe_available(provider: BaseProvider, semaphore: asyncio.Semaphore) -> tuple[bool, str]:
    try:
        async with semaphore:
            return await asyncio.wait_for(provider.available(), timeout=PROBE_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return False, f"availability probe timed out after {PROBE_TIMEOUT_SECONDS:g}s"
    except Exception as exc:
        return False, f"availability probe failed ({type(exc).__name__}: {exc})"


async def select_for_role(
    spec: RoleSpec, context: SelectionContext, semaphore: asyncio.Semaphore | None = None
) -> Selection:
    """Probe every candidate concurrently, then take the first usable one in registry order."""
    if not spec.enabled:
        return Selection(spec.role, None, None, CPU, (), ROLE_DISABLED_REASON)
    gate = semaphore or asyncio.Semaphore(PROBE_CONCURRENCY)
    probes = [_probe(candidate, spec.role, context, spec.dimension, gate) for candidate in spec.candidates]
    results = await asyncio.gather(*probes)
    return _first_usable(spec, results)


def _first_usable(
    spec: RoleSpec, results: Sequence[tuple[ModelCandidate, BaseProvider | None, str]]
) -> Selection:
    annotated = tuple(item[0] for item in results)
    for candidate, provider, device in results:
        if provider is not None:
            log.info(
                "selection.chosen",
                role=spec.role.value,
                runtime=candidate.runtime,
                model=candidate.model,
                device=device,
            )
            return Selection(spec.role, provider, candidate, device, annotated)
    log.warning("selection.none", role=spec.role.value, candidates=len(annotated))
    return Selection(spec.role, None, None, CPU, annotated, NO_CANDIDATE_REASON)
