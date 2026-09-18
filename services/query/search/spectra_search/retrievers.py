"""Stage-1 candidate generators.

Every generator reads a *pre-built index* and nothing else.  None of them opens a
PDF, decodes a video or embeds a corpus: the only embedding that ever happens
here is of the query itself, which is O(1) in corpus size.  That invariant is
what keeps a terabyte-scale deployment on the same query path as a laptop demo.

Each generator is individually failure-tolerant: a store that is down yields an
empty list and a degradation reason, never an exception that loses the other
three retrievers' results.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from spectra_config.logging import get_logger
from spectra_entity_resolution.normalize import enterprise_ids
from spectra_storage.facade import IMAGE_COLLECTION, LEXICAL_INDEX, TEXT_COLLECTION

from .candidates import (
    RETRIEVER_DENSE,
    RETRIEVER_ENTITY,
    RETRIEVER_EXACT,
    RETRIEVER_LEXICAL,
    RETRIEVER_MULTIMODAL,
    Candidate,
    rank_candidates,
)

log = get_logger(__name__)

#: Score attached to an entity-index hit.  The entity index only ever contains
#: links produced by resolution, so a hit there *is* the identity match; the
#: mention's own extraction confidence is carried by the id pattern instead.
ENTITY_INDEX_SCORE = 1.0

#: How many linked chunks a single entity may contribute.  Bounds the cost of a
#: query naming an entity that appears in a million places.
ENTITY_LINK_LIMIT = 200


@dataclass(frozen=True)
class RetrieverOutcome:
    """One retriever's contribution to stage 1."""

    name: str
    candidates: tuple[Candidate, ...] = ()
    detail: str = ""
    degraded_reason: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def count(self) -> int:
        return len(self.candidates)


async def exact_id_candidates(query: str, storage: Any, limit: int) -> tuple[RetrieverOutcome, ...]:
    """Near-free identifier lookup: entity index + lexical phrase query.

    Only runs when the query actually contains an enterprise id, so ordinary
    natural-language questions pay nothing for it.
    """
    identifiers = enterprise_ids(query)
    if not identifiers:
        return (
            RetrieverOutcome(RETRIEVER_ENTITY, detail="no enterprise id in query"),
            RetrieverOutcome(RETRIEVER_EXACT, detail="no enterprise id in query"),
        )
    canonical = [identifier.canonical for identifier in identifiers]
    entity_outcome = await _entity_index_lookup(storage, canonical, limit)
    phrase_outcome = await _phrase_lookup(storage, canonical, limit)
    return (entity_outcome, phrase_outcome)


async def lexical_candidates(
    query: str, storage: Any, filters: dict[str, Any] | None, limit: int
) -> RetrieverOutcome:
    """BM25 / full-text retrieval over the lexical index."""
    if not query.strip():
        return RetrieverOutcome(RETRIEVER_LEXICAL, detail="empty query")
    try:
        matches = await storage.lexical.search(LEXICAL_INDEX, query, limit=limit, filters=filters)
    except Exception as exc:  # noqa: BLE001 - one store down must not kill the search
        log.warning("search.lexical_failed", error=str(exc))
        return RetrieverOutcome(RETRIEVER_LEXICAL, degraded_reason=f"lexical store unavailable: {exc}")
    return RetrieverOutcome(
        RETRIEVER_LEXICAL,
        rank_candidates([m.id for m in matches], RETRIEVER_LEXICAL, [m.score for m in matches]),
        detail=f"bm25 hits={len(matches)}",
    )


async def dense_candidates(
    query: str, storage: Any, gateway: Any | None, filters: dict[str, Any] | None, limit: int
) -> RetrieverOutcome:
    """Dense ANN over the text collection, using a single query embedding."""
    if gateway is None:
        return RetrieverOutcome(RETRIEVER_DENSE, degraded_reason="embedding gateway unavailable")
    if not query.strip():
        return RetrieverOutcome(RETRIEVER_DENSE, detail="empty query")
    try:
        embedded = await gateway.embed_texts([query], is_query=True)
        if not embedded.vectors:
            return RetrieverOutcome(RETRIEVER_DENSE, degraded_reason="embedding returned no vector")
        matches = await storage.vectors.search(
            TEXT_COLLECTION, embedded.vectors[0], limit=limit, filters=filters
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("search.dense_failed", error=str(exc))
        return RetrieverOutcome(RETRIEVER_DENSE, degraded_reason=f"vector store unavailable: {exc}")
    reason = "embedding degraded" if embedded.degraded else None
    return RetrieverOutcome(
        RETRIEVER_DENSE,
        rank_candidates([m.id for m in matches], RETRIEVER_DENSE, [m.score for m in matches]),
        detail=f"ann hits={len(matches)} model={embedded.model}",
        degraded_reason=reason,
    )


async def multimodal_candidates(
    query: str,
    storage: Any,
    gateway: Any | None,
    filters: dict[str, Any] | None,
    limit: int,
    *,
    image_bytes: bytes | None = None,
) -> RetrieverOutcome:
    """Multimodal ANN: text->image via the shared space, image->image directly."""
    if gateway is None:
        return RetrieverOutcome(RETRIEVER_MULTIMODAL, degraded_reason="multimodal gateway unavailable")
    try:
        embedded = await _embed_for_image_space(gateway, query, image_bytes)
        if embedded is None or not embedded.vectors:
            return RetrieverOutcome(RETRIEVER_MULTIMODAL, detail="no multimodal query vector")
        matches = await storage.vectors.search(
            IMAGE_COLLECTION, embedded.vectors[0], limit=limit, filters=filters
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("search.multimodal_failed", error=str(exc))
        return RetrieverOutcome(RETRIEVER_MULTIMODAL, degraded_reason=f"image index unavailable: {exc}")
    return RetrieverOutcome(
        RETRIEVER_MULTIMODAL,
        rank_candidates([m.id for m in matches], RETRIEVER_MULTIMODAL, [m.score for m in matches]),
        detail=f"mm hits={len(matches)} mode={'image' if image_bytes else 'text'}",
    )


async def entity_link_candidates(storage: Any, entity_ids: Sequence[str], limit: int) -> RetrieverOutcome:
    """Chunks linked to known entity ids - the image->everything traversal path."""
    if not entity_ids:
        return RetrieverOutcome(RETRIEVER_ENTITY, detail="no entity ids")
    chunk_ids: list[str] = []
    try:
        for entity_id in entity_ids:
            links = await storage.repository.links_for_entity(entity_id, limit=ENTITY_LINK_LIMIT)
            chunk_ids.extend(link.chunk_id for link in links)
    except Exception as exc:  # noqa: BLE001
        log.warning("search.entity_links_failed", error=str(exc))
        return RetrieverOutcome(RETRIEVER_ENTITY, degraded_reason=f"entity index unavailable: {exc}")
    unique = _unique(chunk_ids)[:limit]
    return RetrieverOutcome(
        RETRIEVER_ENTITY,
        rank_candidates(unique, RETRIEVER_ENTITY, [ENTITY_INDEX_SCORE] * len(unique)),
        detail=f"entities={len(entity_ids)} chunks={len(unique)}",
    )


async def _entity_index_lookup(storage: Any, canonical: Sequence[str], limit: int) -> RetrieverOutcome:
    try:
        entity_ids: list[str] = []
        for key in canonical:
            entities = await storage.repository.find_entities_by_key(key)
            entity_ids.extend(entity.entity_id for entity in entities)
    except Exception as exc:  # noqa: BLE001
        log.warning("search.entity_lookup_failed", error=str(exc))
        return RetrieverOutcome(RETRIEVER_ENTITY, degraded_reason=f"entity index unavailable: {exc}")
    outcome = await entity_link_candidates(storage, _unique(entity_ids), limit)
    return RetrieverOutcome(
        outcome.name,
        outcome.candidates,
        detail=f"ids={','.join(canonical)} {outcome.detail}",
        degraded_reason=outcome.degraded_reason,
        extra={"entity_ids": _unique(entity_ids), "canonical_ids": list(canonical)},
    )


async def _phrase_lookup(storage: Any, canonical: Sequence[str], limit: int) -> RetrieverOutcome:
    collected: list[tuple[str, float]] = []
    try:
        for key in canonical:
            matches = await storage.lexical.search(LEXICAL_INDEX, key, limit=limit, filters=None)
            collected.extend((match.id, match.score) for match in matches)
    except Exception as exc:  # noqa: BLE001
        log.warning("search.phrase_lookup_failed", error=str(exc))
        return RetrieverOutcome(RETRIEVER_EXACT, degraded_reason=f"lexical store unavailable: {exc}")
    best: dict[str, float] = {}
    for chunk_id, score in collected:
        best[chunk_id] = max(best.get(chunk_id, 0.0), float(score))
    ordered = sorted(best.items(), key=lambda item: (-item[1], item[0]))[:limit]
    return RetrieverOutcome(
        RETRIEVER_EXACT,
        rank_candidates([c for c, _ in ordered], RETRIEVER_EXACT, [s for _, s in ordered]),
        detail=f"phrase={','.join(canonical)} hits={len(ordered)}",
    )


async def _embed_for_image_space(gateway: Any, query: str, image_bytes: bytes | None) -> Any | None:
    if image_bytes is not None:
        return await gateway.embed_images([image_bytes])
    if not query.strip():
        return None
    return await gateway.embed_text_for_image_space([query])


def _unique(values: Sequence[str]) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        seen.setdefault(value, None)
    return list(seen)
