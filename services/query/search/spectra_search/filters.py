"""Stage-2 predicates: metadata filters and - non-negotiably - permissions.

Permission filtering is a correctness requirement, not an optimisation, so it is
applied here on hydrated chunk records regardless of what the backing stores did
or did not do with the filter hints we pushed down to them.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from spectra_schemas import Chunk, PermissionContext, SearchFilters, SourceDescriptor

REJECT_FILTER = "filter"
REJECT_PERMISSION = "permission"


def store_filters(filters: SearchFilters) -> dict[str, Any] | None:
    """Filter hints pushed down to the vector / lexical backends.

    Backends may apply them (Qdrant, OpenSearch) or ignore them (a simple
    embedded index); either way stage 2 re-applies the same rules locally.
    """
    if filters.is_empty():
        return None
    payload: dict[str, Any] = {}
    if filters.source_ids:
        payload["source_id"] = list(filters.source_ids)
    if filters.modalities:
        payload["modality"] = [modality.value for modality in filters.modalities]
    if filters.asset_ids:
        payload["asset_id"] = list(filters.asset_ids)
    if filters.entity_ids:
        payload["entities"] = list(filters.entity_ids)
    if filters.media_types:
        payload["media_type"] = list(filters.media_types)
    return payload or None


def matches_filters(chunk: Chunk, filters: SearchFilters) -> bool:
    """True when the chunk satisfies every *requested* facet."""
    if filters.source_ids and chunk.source_id not in filters.source_ids:
        return False
    if filters.modalities and chunk.modality not in filters.modalities:
        return False
    if filters.asset_ids and chunk.asset_id not in filters.asset_ids:
        return False
    if filters.entity_ids and not any(entity in filters.entity_ids for entity in chunk.entities):
        return False
    if filters.media_types and str(chunk.metadata.get("media_type", "")) not in filters.media_types:
        return False
    return _within_window(chunk, filters)


def is_readable(chunk: Chunk, ctx: PermissionContext, source: SourceDescriptor | None) -> bool:
    """True only when this role may read both the source and the chunk itself."""
    source_permissions = list(source.permissions) if source is not None else None
    if not ctx.may_read_source(chunk.source_id, source_permissions):
        return False
    return not chunk.permissions or ctx.role.value in chunk.permissions


def rejection_reason(
    chunk: Chunk, filters: SearchFilters, ctx: PermissionContext, source: SourceDescriptor | None
) -> str | None:
    """``None`` when the chunk survives stage 2, otherwise why it was dropped."""
    if not is_readable(chunk, ctx, source):
        return REJECT_PERMISSION
    if not matches_filters(chunk, filters):
        return REJECT_FILTER
    return None


def _within_window(chunk: Chunk, filters: SearchFilters) -> bool:
    if not filters.occurred_after and not filters.occurred_before:
        return True
    moment = chunk.occurred_at or chunk.created_at
    if moment is None:
        return False
    aware = _aware(moment)
    if filters.occurred_after and aware < _aware(filters.occurred_after):
        return False
    if filters.occurred_before and aware > _aware(filters.occurred_before):
        return False
    return True


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
