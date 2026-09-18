"""Turning retrieval output into citable :class:`EvidenceItem` objects.

The evidence service owns this conversion in production; the Brain calls it
through this adapter and keeps a deterministic local conversion as the fallback
path, so a degraded evidence service costs provenance enrichment but never
costs the investigation its citations.
"""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from typing import Any

from spectra_config.logging import get_logger
from spectra_schemas import (
    DatabaseLocator,
    EvidenceItem,
    EvidenceKind,
    EvidenceStance,
    Modality,
    Provenance,
    SearchHit,
    evidence_id,
)

log = get_logger(__name__)

# A system-of-record row is the highest-reliability evidence class SPECTRA has:
# it is the operational truth other modalities merely describe.
DATABASE_RELIABILITY = 0.9
# An exact identifier match against that system of record is maximally relevant.
EXACT_MATCH_RELEVANCE = 0.9
# Excerpt length kept short enough to fit many items into one grounding prompt.
MAX_EXCERPT_CHARS = 600
MAX_SUMMARY_CHARS = 240

_KIND_BY_MODALITY: dict[Modality, EvidenceKind] = {
    Modality.DOCUMENT: EvidenceKind.DOCUMENT,
    Modality.IMAGE: EvidenceKind.IMAGE,
    Modality.VIDEO: EvidenceKind.VIDEO,
    Modality.AUDIO: EvidenceKind.AUDIO,
    Modality.DATABASE: EvidenceKind.DATABASE,
    Modality.GRAPH: EvidenceKind.GRAPH,
    Modality.EXTERNAL: EvidenceKind.EXTERNAL_API,
}


async def maybe_await(value: Any) -> Any:
    """Await ``value`` when a peer service returned a coroutine."""
    if inspect.isawaitable(value):
        return await value
    return value


def first_sentence(text: str) -> str:
    """The first complete sentence, so a mid-word snippet cut never reaches the answer."""
    collapsed = " ".join((text or "").split())
    for index, char in enumerate(collapsed):
        if char in ".!?" and index + 1 < len(collapsed) and collapsed[index + 1] == " ":
            return collapsed[: index + 1]
    return collapsed


def summarise(text: str, limit: int = MAX_SUMMARY_CHARS) -> str:
    collapsed = " ".join((text or "").split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rsplit(" ", 1)[0] + "…"


async def evidence_from_hits(
    hits: Sequence[SearchHit],
    *,
    retrieved_by: str,
    services: Any | None = None,
    stance: EvidenceStance = EvidenceStance.NEUTRAL,
) -> list[EvidenceItem]:
    """Convert search hits to evidence, preferring the evidence service builder."""
    built = await _builder_call(services, "from_search_hits", hits)
    if built is None:
        built = [_local_from_hit(hit, retrieved_by) for hit in hits]
    return [
        item.model_copy(update={"retrieved_by": retrieved_by, "stance": stance})
        for item in built
        if isinstance(item, EvidenceItem)
    ]


async def evidence_from_records(
    rows: Sequence[dict[str, Any]],
    *,
    source_id: str,
    table: str,
    primary_key: str,
    retrieved_by: str,
    services: Any | None = None,
    stance: EvidenceStance = EvidenceStance.NEUTRAL,
) -> list[EvidenceItem]:
    """Convert database rows to evidence, preferring the evidence service builder."""
    built = await _builder_call(services, "from_database_rows", rows)
    if built is None:
        built = [
            _local_from_row(row, source_id=source_id, table=table, primary_key=primary_key)
            for row in rows
        ]
    return [
        item.model_copy(update={"retrieved_by": retrieved_by, "stance": stance})
        for item in built
        if isinstance(item, EvidenceItem)
    ]


async def _builder_call(services: Any | None, method: str, payload: Sequence[Any]) -> list[Any] | None:
    builder = getattr(services, "builder", None) if services is not None else None
    func = getattr(builder, method, None)
    if func is None or not payload:
        return None if func is None else []
    try:
        return list(await maybe_await(func(list(payload))))
    except Exception as exc:
        log.warning("evidence.builder_failed", method=method, error=str(exc))
        return None


def _local_from_hit(hit: SearchHit, retrieved_by: str) -> EvidenceItem:
    text = hit.text or hit.snippet
    reliability = hit.scores.source_reliability
    return EvidenceItem(
        evidence_id=evidence_id(hit.chunk_id, retrieved_by),
        kind=_KIND_BY_MODALITY.get(hit.modality, EvidenceKind.DOCUMENT),
        modality=hit.modality,
        summary=summarise(first_sentence(hit.snippet or text) or hit.title or hit.chunk_id),
        excerpt=summarise(text, MAX_EXCERPT_CHARS),
        provenance=hit.provenance,
        relevance=max(0.0, min(1.0, hit.score)),
        reliability=reliability,
        reliability_reason=f"source '{hit.source_id}' rated {reliability:.2f} at retrieval",
        entities=list(hit.entities),
        occurred_at=hit.occurred_at,
        retrieved_by=retrieved_by,
    )


def _local_from_row(
    row: dict[str, Any],
    *,
    source_id: str,
    table: str,
    primary_key: str,
) -> EvidenceItem:
    record_id = str(row.get(primary_key) or row.get("id") or row.get("record_id") or "")
    locator = DatabaseLocator(
        source_id=source_id,
        table=table,
        primary_key=primary_key,
        record_id=record_id,
    )
    provenance = Provenance(
        source_id=source_id,
        modality=Modality.DATABASE,
        object_uri=f"spectra://records/{source_id}/{table}/{record_id}",
        locator=locator,
    )
    return EvidenceItem(
        evidence_id=evidence_id(f"{source_id}:{table}:{record_id}", "database"),
        kind=EvidenceKind.DATABASE,
        modality=Modality.DATABASE,
        summary=summarise(f"{table} record {record_id}: {render_row(row)}"),
        excerpt=summarise(render_row(row), MAX_EXCERPT_CHARS),
        provenance=provenance,
        relevance=EXACT_MATCH_RELEVANCE,
        reliability=DATABASE_RELIABILITY,
        reliability_reason="system-of-record row retrieved by exact key match",
        occurred_at=_row_timestamp(row),
        retrieved_by="query_database",
    )


def render_row(row: dict[str, Any]) -> str:
    return "; ".join(f"{key}={value}" for key, value in row.items() if value not in (None, ""))


def _row_timestamp(row: dict[str, Any]) -> Any:
    from datetime import datetime

    for key in ("occurred_at", "created_at", "timestamp", "event_time", "updated_at"):
        value = row.get(key)
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
    return None
