"""Opening one stored asset at an exact locator.

The document, vision, video and brain agents all take the same three steps when
a claim has to be read where it came from: reach the repository, fetch an asset
the caller is permitted to read, and turn one of its chunks into citable
evidence.  Those steps live here so all four agents stay identical about
permissions and provenance.
"""

from __future__ import annotations

from typing import Any

from spectra_schemas import (
    EvidenceItem,
    EvidenceKind,
    Provenance,
    ToolError,
    evidence_id,
)

from ..context import ToolContext
from ..evidence_adapter import maybe_await, summarise
from .base import require_service

# Opening a specific locator is a targeted read, so its evidence is maximally
# relevant by construction; reliability still comes from the source.
LOCATOR_RELEVANCE = 0.95
DEFAULT_SOURCE_RELIABILITY = 0.7


async def repository_for(ctx: ToolContext, tool: str) -> Any:
    storage = require_service(ctx, "storage", tool)
    repository = getattr(storage, "repository", None)
    if repository is None:
        raise ToolError(tool, "storage exposes no repository")
    return repository


async def asset_for(ctx: ToolContext, tool: str, asset_id: str) -> Any:
    repository = await repository_for(ctx, tool)
    asset = await maybe_await(repository.get_asset(asset_id))
    if asset is None:
        raise ToolError(tool, f"no asset with id '{asset_id}'")
    if not ctx.permissions.may_read_source(asset.source_id, getattr(asset, "permissions", None)):
        raise ToolError(tool, f"role '{ctx.permissions.role.value}' may not read source {asset.source_id}")
    return asset


def locator_value(chunk: Any, key: str) -> Any:
    provenance = getattr(chunk, "provenance", None) or {}
    locator = provenance.get("locator") if isinstance(provenance, dict) else None
    if isinstance(locator, dict) and key in locator:
        return locator[key]
    metadata = getattr(chunk, "metadata", None) or {}
    return metadata.get(key)


def evidence_for_chunk(
    chunk: Any, asset: Any, provenance: Provenance, kind: EvidenceKind, tool: str
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id(chunk.chunk_id, tool),
        kind=kind,
        modality=provenance.modality,
        summary=summarise(chunk.text or chunk.title or asset.title),
        excerpt=summarise(chunk.text or "", 600),
        provenance=provenance,
        relevance=LOCATOR_RELEVANCE,
        reliability=DEFAULT_SOURCE_RELIABILITY,
        reliability_reason="opened directly at the cited locator",
        entities=list(getattr(chunk, "entities", []) or []),
        retrieved_by=tool,
    )
