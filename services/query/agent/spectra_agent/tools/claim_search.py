"""Fan-out retrieval for a single claim across the enabled modalities.

Used by the supporting/disconfirming evidence tools and by the disproof agent,
so the same claim is always chased the same way.  Independent modality searches
run concurrently; the GPU-bound ones still queue behind the single GPU slot.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from spectra_config.logging import get_logger
from spectra_schemas import EvidenceItem, Modality

from ..context import ToolContext
from ..evidence_adapter import evidence_from_hits
from ..gpu import GpuScheduler
from .search_gateway import build_request, run_search

log = get_logger(__name__)

MODALITY_FLAGS: dict[Modality, str] = {
    Modality.DOCUMENT: "document",
    Modality.IMAGE: "image",
    Modality.VIDEO: "video",
    Modality.AUDIO: "audio",
}
GPU_MODALITIES: frozenset[Modality] = frozenset({Modality.IMAGE, Modality.VIDEO})
DEFAULT_MODALITIES: tuple[Modality, ...] = (
    Modality.DOCUMENT,
    Modality.AUDIO,
    Modality.IMAGE,
    Modality.VIDEO,
)


def enabled_modalities(ctx: ToolContext, requested: Sequence[Modality] | None = None) -> list[Modality]:
    candidates = list(requested or DEFAULT_MODALITIES)
    return [m for m in candidates if ctx.flag_enabled(MODALITY_FLAGS.get(m))]


async def search_claim(
    ctx: ToolContext,
    *,
    tool: str,
    query: str,
    top_k: int,
    modalities: Sequence[Modality] | None = None,
) -> list[EvidenceItem]:
    """Retrieve evidence for one claim from every enabled modality."""
    targets = enabled_modalities(ctx, modalities)
    if not targets:
        return []
    results = await asyncio.gather(
        *(_one_modality(ctx, tool, query, top_k, modality) for modality in targets),
        return_exceptions=True,
    )
    items: list[EvidenceItem] = []
    seen: set[str] = set()
    for modality, result in zip(targets, results, strict=True):
        if isinstance(result, BaseException):
            log.warning("claim_search.modality_failed", modality=modality.value, error=str(result))
            continue
        for item in result:
            if item.evidence_id not in seen:
                seen.add(item.evidence_id)
                items.append(item)
    return items


async def _one_modality(
    ctx: ToolContext, tool: str, query: str, top_k: int, modality: Modality
) -> list[EvidenceItem]:
    request = build_request(query=query, modality=modality, top_k=top_k, mode=ctx.mode)

    async def _call() -> list[EvidenceItem]:
        response = await run_search(ctx, tool=tool, request=request, modality=modality)
        return await evidence_from_hits(
            response.hits, retrieved_by=tool, services=ctx.services.evidence
        )

    if modality in GPU_MODALITIES:
        return await GpuScheduler.run(_call, label=f"{tool}:{modality.value}")
    return await _call()
