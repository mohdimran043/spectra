"""Thin adapter over the injected SearchService.

Modality retrieval is expressed as a ``SearchRequest`` with a modality filter -
the contract every caller can rely on - and the service's optional
``search_modality`` fast path is used when it exposes one.
"""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from spectra_schemas import (
    Modality,
    SearchFilters,
    SearchHit,
    SearchMode,
    SearchRequest,
    SearchResponse,
    ToolError,
)

from ..context import ToolContext
from .base import require_service


def build_request(
    *,
    query: str,
    modality: Modality | None,
    top_k: int,
    mode: SearchMode,
    source_ids: Sequence[str] = (),
    asset_ids: Sequence[str] = (),
    occurred_after: datetime | None = None,
    occurred_before: datetime | None = None,
) -> SearchRequest:
    filters = SearchFilters(
        modalities=[modality] if modality else [],
        source_ids=list(source_ids),
        asset_ids=list(asset_ids),
        occurred_after=occurred_after,
        occurred_before=occurred_before,
    )
    return SearchRequest(query=query, mode=mode, top_k=top_k, filters=filters, include_text=True)


async def run_search(
    ctx: ToolContext,
    *,
    tool: str,
    request: SearchRequest,
    modality: Modality | None = None,
    image_asset_id: str | None = None,
) -> SearchResponse:
    """Execute a search through whichever entry point the service exposes."""
    service = require_service(ctx, "search", tool)
    if image_asset_id:
        by_image = getattr(service, "search_by_image", None)
        if by_image is None:
            raise ToolError(tool, "the search service does not support image-to-anything search")
        return _as_response(await by_image(image_asset_id, ctx.permissions), request, tool)

    specialised = getattr(service, "search_modality", None)
    if modality is not None and specialised is not None and _accepts_three_args(specialised):
        return _as_response(await specialised(request, modality, ctx.permissions), request, tool)

    plain = getattr(service, "search", None)
    if plain is None:
        raise ToolError(tool, "the search service exposes no search entry point")
    return _as_response(await plain(request, ctx.permissions), request, tool)


def _accepts_three_args(func: Any) -> bool:
    try:
        parameters = [
            p
            for p in inspect.signature(func).parameters.values()
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        ]
    except (TypeError, ValueError):  # pragma: no cover - builtins / mocks
        return False
    return len(parameters) >= 3


def _as_response(value: Any, request: SearchRequest, tool: str) -> SearchResponse:
    if isinstance(value, SearchResponse):
        return value
    if isinstance(value, list) and all(isinstance(hit, SearchHit) for hit in value):
        return SearchResponse(query=request.query, mode=request.mode, hits=value, total_candidates=len(value))
    raise ToolError(tool, f"search service returned an unsupported payload: {type(value).__name__}")
