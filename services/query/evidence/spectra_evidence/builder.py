"""Turn retrieval output into citable evidence.

The builder is the only place where a search hit or a database row becomes an
``EvidenceItem``.  Summaries are *extractive* - the most informative sentence
that already exists in the chunk - so nothing the user reads was invented here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
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
    SourceDescriptor,
    evidence_id,
)

from .locators import locator_signature
from .reliability import ReliabilityScorer
from .text_utils import (
    MAX_EXCERPT_CHARS,
    MAX_SUMMARY_CHARS,
    excerpt_around,
    extractive_summary,
    matched_terms,
    truncate,
)

log = get_logger(__name__)

# A primary-key row match answers the lookup exactly, so it enters the ledger at
# full relevance; ranked search hits carry their own (already normalised) score.
DATABASE_ROW_RELEVANCE = 1.0
# How many columns are rendered into a row summary before it stops being a
# readable citation; the full row still lives in the excerpt.
MAX_ROW_SUMMARY_FIELDS = 8
# Rows come from live tables, so "current" is the honest default version status.
DEFAULT_RECORD_VERSION_STATUS = "current"

_KIND_BY_MODALITY: Mapping[Modality, EvidenceKind] = {
    Modality.DOCUMENT: EvidenceKind.DOCUMENT,
    Modality.IMAGE: EvidenceKind.IMAGE,
    Modality.VIDEO: EvidenceKind.VIDEO,
    Modality.AUDIO: EvidenceKind.AUDIO,
    Modality.DATABASE: EvidenceKind.DATABASE,
    Modality.GRAPH: EvidenceKind.GRAPH,
    Modality.EXTERNAL: EvidenceKind.EXTERNAL_API,
}


@dataclass(frozen=True)
class _RowContext:
    """Everything a batch of database rows shares, resolved once per call."""

    source_id: str
    source_name: str | None
    table: str
    primary_key: str
    claim_scope: str
    entity_ids: tuple[str, ...]
    retrieved_by: str
    stance: EvidenceStance
    version_status: str
    occurred_at_key: str | None
    corroboration_count: int
    scorer: ReliabilityScorer
    now: datetime


class EvidenceBuilder:
    """Builds evidence items; never mutates the hits it is given."""

    def __init__(self, scorer: ReliabilityScorer | None = None) -> None:
        self._scorer = scorer or ReliabilityScorer()

    @property
    def scorer(self) -> ReliabilityScorer:
        return self._scorer

    # -- search hits ------------------------------------------------------
    def from_search_hits(
        self,
        hits: Sequence[SearchHit],
        *,
        claim_scope: str = "",
        entity_ids: Sequence[str] = (),
        entity_terms: Sequence[str] = (),
        retrieved_by: str = "",
        stance: EvidenceStance = EvidenceStance.NEUTRAL,
        sources: Mapping[str, SourceDescriptor] | None = None,
        now: datetime | None = None,
    ) -> list[EvidenceItem]:
        """Convert ranked hits into evidence, scoring reliability per hit."""
        if not hits:
            return []
        scorer = self._scorer.with_sources(sources) if sources else self._scorer
        keys = _unique(list(entity_ids) + list(entity_terms))
        corroboration = _corroboration_counts(hits, keys)
        moment = now or datetime.now(timezone.utc)
        items = [
            self._item_from_hit(
                hit,
                keys=keys,
                entity_ids=entity_ids,
                claim_scope=claim_scope,
                retrieved_by=retrieved_by,
                stance=stance,
                scorer=scorer,
                corroboration=corroboration.get(hit.chunk_id, 0),
                now=moment,
            )
            for hit in hits
        ]
        log.debug("evidence.built_from_hits", count=len(items), claim_scope=claim_scope)
        return items

    def _item_from_hit(
        self,
        hit: SearchHit,
        *,
        keys: Sequence[str],
        entity_ids: Sequence[str],
        claim_scope: str,
        retrieved_by: str,
        stance: EvidenceStance,
        scorer: ReliabilityScorer,
        corroboration: int,
        now: datetime,
    ) -> EvidenceItem:
        body = hit.text or hit.snippet or ""
        named_terms = matched_terms(f"{hit.title or ''} {body}", keys)
        linked = [key for key in keys if key in hit.entities]
        entity_named = bool(named_terms or linked)
        summary = extractive_summary(body, keys) or truncate(hit.snippet or hit.title or "", MAX_SUMMARY_CHARS)
        kind = _kind_for_hit(hit)
        reliability, reason = scorer.score(
            hit.provenance,
            corroboration_count=corroboration,
            entity_named=entity_named,
            entity_label=(named_terms or linked or [None])[0],
            kind=kind,
            now=now,
        )
        return EvidenceItem(
            evidence_id=evidence_id(hit.chunk_id, claim_scope),
            kind=kind,
            modality=hit.modality,
            summary=summary,
            excerpt=truncate(hit.snippet, MAX_EXCERPT_CHARS) or excerpt_around(body, summary),
            provenance=hit.provenance,
            stance=stance,
            relevance=_clamp(hit.score),
            reliability=reliability,
            reliability_reason=reason,
            entities=_unique(list(hit.entities) + linked + [e for e in entity_ids if e in named_terms]),
            occurred_at=hit.occurred_at,
            retrieved_at=now,
            retrieved_by=retrieved_by,
        )

    # -- database rows ----------------------------------------------------
    def from_database_rows(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        source_id: str,
        table: str,
        primary_key: str,
        claim_scope: str = "",
        entity_ids: Sequence[str] = (),
        retrieved_by: str = "",
        stance: EvidenceStance = EvidenceStance.NEUTRAL,
        source_name: str | None = None,
        version_status: str = DEFAULT_RECORD_VERSION_STATUS,
        occurred_at_key: str | None = None,
        corroboration_count: int = 0,
        sources: Mapping[str, SourceDescriptor] | None = None,
        now: datetime | None = None,
    ) -> list[EvidenceItem]:
        """Convert database rows into evidence with row-level provenance."""
        context = _RowContext(
            source_id=source_id,
            source_name=source_name,
            table=table,
            primary_key=primary_key,
            claim_scope=claim_scope,
            entity_ids=tuple(entity_ids),
            retrieved_by=retrieved_by,
            stance=stance,
            version_status=version_status,
            occurred_at_key=occurred_at_key,
            corroboration_count=corroboration_count,
            scorer=self._scorer.with_sources(sources) if sources else self._scorer,
            now=now or datetime.now(timezone.utc),
        )
        items: list[EvidenceItem] = []
        for row in rows:
            record_id = str(row.get(primary_key) or "").strip()
            if not record_id:
                log.warning("evidence.row_without_primary_key", table=table, primary_key=primary_key)
                continue
            items.append(self._item_from_row(row, record_id, context))
        log.debug("evidence.built_from_rows", count=len(items), table=table)
        return items

    def _item_from_row(
        self, row: Mapping[str, Any], record_id: str, context: _RowContext
    ) -> EvidenceItem:
        rendered = _render_row(row, context.primary_key)
        occurred_at = (
            _coerce_datetime(row.get(context.occurred_at_key)) if context.occurred_at_key else None
        )
        provenance = _row_provenance(
            record_id=record_id,
            source_id=context.source_id,
            source_name=context.source_name,
            table=context.table,
            primary_key=context.primary_key,
            version_status=context.version_status,
            occurred_at=occurred_at,
        )
        # A primary-key row names its own record explicitly; when the caller asked
        # about other entities it only counts if the row actually mentions them.
        entity_ids = context.entity_ids
        named = not entity_ids or record_id in entity_ids or bool(matched_terms(rendered, entity_ids))
        reliability, reason = context.scorer.score(
            provenance,
            corroboration_count=context.corroboration_count,
            entity_named=named,
            entity_label=record_id,
            kind=EvidenceKind.DATABASE,
            now=context.now,
        )
        summary = f"{record_id}: {_render_row(row, context.primary_key, MAX_ROW_SUMMARY_FIELDS)}"
        return EvidenceItem(
            evidence_id=evidence_id(
                f"{context.source_id}:{context.table}:{record_id}", context.claim_scope
            ),
            kind=EvidenceKind.DATABASE,
            modality=Modality.DATABASE,
            summary=truncate(summary, MAX_SUMMARY_CHARS),
            excerpt=truncate(rendered, MAX_EXCERPT_CHARS),
            provenance=provenance,
            stance=context.stance,
            relevance=DATABASE_ROW_RELEVANCE,
            reliability=reliability,
            reliability_reason=reason,
            entities=_unique([record_id, *entity_ids]),
            occurred_at=occurred_at,
            retrieved_at=context.now,
            retrieved_by=context.retrieved_by,
        )

    # -- dedupe -----------------------------------------------------------
    @staticmethod
    def deduplicate(items: Sequence[EvidenceItem]) -> list[EvidenceItem]:
        """Collapse items sharing an asset + locator, keeping the strongest."""
        best: dict[tuple[Any, ...], EvidenceItem] = {}
        order: list[tuple[Any, ...]] = []
        for item in items:
            signature = locator_signature(item.provenance)
            current = best.get(signature)
            if current is None:
                best[signature] = item
                order.append(signature)
                continue
            # Deterministic tie-break on evidence_id keeps reruns identical.
            if (item.weight, item.evidence_id) > (current.weight, current.evidence_id):
                best[signature] = item
        dropped = len(items) - len(order)
        if dropped:
            log.debug("evidence.deduplicated", dropped=dropped, kept=len(order))
        return [best[signature] for signature in order]


def _row_provenance(
    *,
    record_id: str,
    source_id: str,
    source_name: str | None,
    table: str,
    primary_key: str,
    version_status: str,
    occurred_at: datetime | None,
) -> Provenance:
    """Row-level provenance; the row's own event time is its best record date."""
    return Provenance(
        source_id=source_id,
        source_name=source_name,
        modality=Modality.DATABASE,
        object_uri=f"spectra://records/{source_id}/{table}/{record_id}",
        locator=DatabaseLocator(
            source_id=source_id, table=table, primary_key=primary_key, record_id=record_id
        ),
        version_status=version_status,
        created_at=occurred_at,
        modified_at=occurred_at,
    )


def _corroboration_counts(hits: Sequence[SearchHit], keys: Sequence[str]) -> dict[str, int]:
    """For each hit, how many OTHER distinct sources mention the same entity."""
    matched_by_hit: dict[str, set[str]] = {}
    sources_by_key: dict[str, set[str]] = {}
    for hit in hits:
        text = f"{hit.title or ''} {hit.text or hit.snippet or ''}"
        found = {key for key in keys if key in hit.entities} | set(matched_terms(text, keys))
        matched_by_hit[hit.chunk_id] = found
        for key in found:
            sources_by_key.setdefault(key, set()).add(hit.source_id)
    counts: dict[str, int] = {}
    for hit in hits:
        others: set[str] = set()
        for key in matched_by_hit[hit.chunk_id]:
            others |= sources_by_key[key]
        others.discard(hit.source_id)
        counts[hit.chunk_id] = len(others)
    return counts


def _kind_for_hit(hit: SearchHit) -> EvidenceKind:
    declared = hit.metadata.get("evidence_kind")
    if declared:
        try:
            return EvidenceKind(str(declared))
        except ValueError:
            log.warning("evidence.unknown_kind_in_metadata", value=str(declared), chunk_id=hit.chunk_id)
    return _KIND_BY_MODALITY.get(hit.modality, EvidenceKind.EXTERNAL_API)


def _render_row(row: Mapping[str, Any], primary_key: str, limit: int | None = None) -> str:
    fields = [
        f"{key}={value}"
        for key, value in row.items()
        if key != primary_key and value is not None and str(value).strip() != ""
    ]
    if limit is not None:
        fields = fields[:limit]
    return ", ".join(fields)


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            log.warning("evidence.unparsable_timestamp", value=value)
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _unique(values: Sequence[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return seen


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


__all__ = ["DATABASE_ROW_RELEVANCE", "EvidenceBuilder"]
