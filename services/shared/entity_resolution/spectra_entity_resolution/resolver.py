"""The entity-resolution cascade.

Six steps, cheapest and most certain first, short-circuiting as soon as the
answer is not in doubt:

1. **exact** canonical-key match      - free, deterministic, confidence 1.0
2. **normalized** alternate-key match - free, deterministic (person initials /
   surname keys, unpadded id forms)
3. **fuzzy**    - rapidfuzz over a bounded repository candidate pool
4. **semantic** - embeddings of the surface against candidate names
5. **database** - the system of record, through an *injected* callable so this
   package never imports the connectors package
6. **LLM verification** - only when the top two candidates are within
   :data:`AMBIGUITY_MARGIN`.  If the gateway is degraded the resolution is marked
   ``needs_verification`` and nothing is guessed.

Every step contributes ranked :class:`ResolutionCandidate` rows, so the returned
:class:`EntityResolution` is a complete audit trail and not just an answer.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from spectra_config.logging import get_logger
from spectra_schemas import (
    CanonicalEntity,
    Chunk,
    EntityLink,
    EntityMention,
    EntityResolution,
    EntityType,
    ResolutionCandidate,
)
from spectra_schemas.ids import entity_id as make_entity_id

from .canonical import create_entity, entity_from_row, extend_entity, mention_key
from .extractor import EntityExtractor
from .matching import (
    CANDIDATE_POOL_LIMIT,
    SEMANTIC_COSINE_THRESHOLD,
    best_fuzzy_match,
    cosine_similarity,
    surfaces_of,
)
from .normalize import enterprise_ids, normalized_keys_for
from .patterns import PERSON_SEQUENCE
from .verification import verify_candidates

log = get_logger(__name__)

METHOD_EXACT = "exact"
METHOD_NORMALIZED = "normalized"
METHOD_FUZZY = "fuzzy"
METHOD_SEMANTIC = "semantic"
METHOD_DATABASE = "database"
METHOD_LLM = "llm"
METHOD_NONE = "none"

# ---------------------------------------------------------------------------
# Confidence ladder.  The ordering is the contract: a deterministic key match can
# never be beaten by a probabilistic one, and the system of record sits just
# below an exact key because a row can be stale but is never ambiguous.
# ---------------------------------------------------------------------------
EXACT_CONFIDENCE = 1.0
DATABASE_CONFIDENCE = 0.97
NORMALIZED_CONFIDENCE = 0.95

#: Fuzzy/semantic scores at or above these are accepted without further steps,
#: provided the runner-up is more than AMBIGUITY_MARGIN behind.
FUZZY_AUTO_ACCEPT = 0.95
SEMANTIC_AUTO_ACCEPT = 0.88

#: Two candidates this close are, for practical purposes, tied - that is exactly
#: the situation an LLM verification call is worth paying for.
AMBIGUITY_MARGIN = 0.05

DbLookup = Callable[[str, str], Awaitable[Mapping[str, Any] | None] | Mapping[str, Any] | None]


class EntityResolver:
    """Resolve surface forms onto canonical entities."""

    def __init__(
        self,
        repository: Any,
        *,
        gateway: Any | None = None,
        db_lookup: DbLookup | None = None,
        extractor: EntityExtractor | None = None,
    ) -> None:
        self._repository = repository
        self._gateway = gateway
        self._db_lookup = db_lookup
        self._extractor = extractor or EntityExtractor()

    # -- public API -------------------------------------------------------
    async def resolve(
        self, surface: str, entity_type: EntityType | None = None, *, context: str = ""
    ) -> EntityResolution:
        """Run the cascade for one surface form."""
        cleaned = surface.strip()
        resolved_type = entity_type or self.infer_type(cleaned)
        keys = normalized_keys_for(cleaned, resolved_type)
        canonical_key = keys[0] if keys else ""
        known: dict[str, CanonicalEntity] = {}

        key_hits: list[ResolutionCandidate] = []
        for step_keys, method, confidence in (
            (keys[:1], METHOD_EXACT, EXACT_CONFIDENCE),
            (keys[1:], METHOD_NORMALIZED, NORMALIZED_CONFIDENCE),
        ):
            hits = await self._match_keys(step_keys, resolved_type, method, known)
            if len(hits) == 1:
                return self._resolution(cleaned, canonical_key, hits, method, confidence, known)
            key_hits.extend(hits)

        # Two entities under one key is an ambiguity, not an answer: keep both as
        # candidates and let the later, more discriminating steps decide.
        candidates = key_hits + await self._similarity_candidates(cleaned, resolved_type, known)
        decisive = _decisive(candidates, FUZZY_AUTO_ACCEPT, METHOD_FUZZY) or _decisive(
            candidates, SEMANTIC_AUTO_ACCEPT, METHOD_SEMANTIC
        )
        if decisive is not None:
            return self._resolution(cleaned, canonical_key, candidates, decisive.method, decisive.score, known)

        database = await self._database_candidate(resolved_type, canonical_key, known)
        if database is not None:
            return self._resolution(
                cleaned, canonical_key, [database, *candidates], METHOD_DATABASE, DATABASE_CONFIDENCE, known
            )
        return await self._finalise(cleaned, canonical_key, resolved_type, candidates, known, context)

    async def resolve_batch(
        self, surfaces: Sequence[str], entity_type: EntityType | None = None
    ) -> list[EntityResolution]:
        """Resolve many surfaces.  Sequential by design: each resolution may create
        state the next one should see, and the cascade is I/O-cheap."""
        return [await self.resolve(surface, entity_type) for surface in surfaces]

    async def link_mentions(self, chunk: Chunk, mentions: Sequence[EntityMention]) -> list[EntityLink]:
        """Turn mentions found in ``chunk`` into ``chunk REFERS_TO entity`` edges."""
        links: list[EntityLink] = []
        for mention in mentions:
            resolution = await self.resolve(mention.surface, mention.entity_type)
            identifier = (
                resolution.resolved.entity_id
                if resolution.resolved is not None
                else make_entity_id(mention.entity_type.value, mention.normalized)
            )
            links.append(
                EntityLink(
                    entity_id=identifier,
                    chunk_id=chunk.chunk_id,
                    asset_id=chunk.asset_id,
                    source_id=chunk.source_id,
                    modality=chunk.modality,
                    surface=mention.surface,
                    confidence=min(mention.confidence, max(resolution.confidence, mention.confidence)),
                )
            )
        return links

    async def merge_into_canonical(self, mentions: Sequence[EntityMention]) -> list[CanonicalEntity]:
        """Create or extend the canonical entities a batch of mentions implies.

        Entities are never mutated: every update builds a new model via
        ``model_copy``.  Mentions are processed strongest-first so the most
        explicit surface form becomes the canonical name.
        """
        ordered = sorted(mentions, key=lambda m: (-m.confidence, -len(m.surface), m.surface))
        merged: dict[str, CanonicalEntity] = {}
        for mention in ordered:
            resolution = await self.resolve(mention.surface, mention.entity_type)
            existing = resolution.resolved or merged.get(mention_key(mention))
            entity = extend_entity(existing, mention) if existing else create_entity(mention)
            stored = await self._repository.upsert_entity(entity)
            merged[stored.entity_id] = stored
            merged[mention_key(mention)] = stored
        return [entity for key, entity in merged.items() if key == entity.entity_id]

    def infer_type(self, surface: str) -> EntityType:
        """Best-effort type for a bare surface form."""
        identifiers = enterprise_ids(surface)
        if identifiers:
            return identifiers[0].entity_type
        if PERSON_SEQUENCE.fullmatch(surface.strip()) or _looks_like_single_name(surface):
            return EntityType.PERSON
        return EntityType.OTHER

    # -- cascade steps ----------------------------------------------------
    async def _match_keys(
        self,
        keys: Sequence[str],
        entity_type: EntityType,
        method: str,
        known: dict[str, CanonicalEntity],
    ) -> list[ResolutionCandidate]:
        for key in keys:
            if not key:
                continue
            entities = await self._repository.find_entities_by_key(key)
            matches = [entity for entity in entities if _type_compatible(entity, entity_type)]
            if not matches:
                continue
            score = EXACT_CONFIDENCE if method == METHOD_EXACT else NORMALIZED_CONFIDENCE
            return [_candidate(entity, score, method, f"key {key!r}", known) for entity in matches]
        return []

    async def _similarity_candidates(
        self, surface: str, entity_type: EntityType, known: dict[str, CanonicalEntity]
    ) -> list[ResolutionCandidate]:
        pool = await self._repository.search_entities(surface, limit=CANDIDATE_POOL_LIMIT)
        pool = [entity for entity in pool if _type_compatible(entity, entity_type)]
        if not pool:
            return []
        fuzzy = [
            _candidate(entity, match.score, METHOD_FUZZY, f"{match.metric} vs {match.matched_alias!r}", known)
            for entity, match in ((entity, best_fuzzy_match(surface, entity)) for entity in pool)
            if match is not None
        ]
        semantic = await self._semantic_candidates(surface, pool, known)
        return _rank(fuzzy + semantic)

    async def _semantic_candidates(
        self, surface: str, pool: Sequence[CanonicalEntity], known: dict[str, CanonicalEntity]
    ) -> list[ResolutionCandidate]:
        if self._gateway is None or not pool:
            return []
        names = [surfaces_of(entity)[0] for entity in pool]
        try:
            query = await self._gateway.embed_texts([surface], is_query=True)
            documents = await self._gateway.embed_texts(names)
        except Exception as exc:  # noqa: BLE001 - embedding outage must not break resolution
            log.warning("entity.semantic_step_failed", surface=surface, error=str(exc))
            return []
        if query.degraded or documents.degraded or not query.vectors:
            return []
        scored = [
            (entity, cosine_similarity(query.vectors[0], vector))
            for entity, vector in zip(pool, documents.vectors, strict=False)
        ]
        return [
            _candidate(entity, score, METHOD_SEMANTIC, f"cosine={score:.3f}", known)
            for entity, score in scored
            if score >= SEMANTIC_COSINE_THRESHOLD
        ]

    async def _database_candidate(
        self, entity_type: EntityType, value: str, known: dict[str, CanonicalEntity]
    ) -> ResolutionCandidate | None:
        if self._db_lookup is None or not value:
            return None
        try:
            row = self._db_lookup(entity_type.value, value)
            if inspect.isawaitable(row):
                row = await row
        except Exception as exc:  # noqa: BLE001 - a down connector degrades, never raises here
            log.warning("entity.database_step_failed", value=value, error=str(exc))
            return None
        if not row:
            return None
        entity = entity_from_row(entity_type, value, dict(row))
        stored = await self._repository.upsert_entity(entity)
        return _candidate(stored, DATABASE_CONFIDENCE, METHOD_DATABASE, "system-of-record row", known)

    async def _finalise(
        self,
        surface: str,
        canonical_key: str,
        entity_type: EntityType,
        candidates: list[ResolutionCandidate],
        known: dict[str, CanonicalEntity],
        context: str,
    ) -> EntityResolution:
        if not candidates:
            return EntityResolution(
                query=surface,
                normalized=canonical_key,
                method=METHOD_NONE,
                confidence=0.0,
                explanation=f"No candidate matched {canonical_key!r} through any cascade step.",
            )
        ranked = _rank(candidates)
        if len(ranked) > 1 and (ranked[0].score - ranked[1].score) > AMBIGUITY_MARGIN:
            return self._resolution(surface, canonical_key, ranked, ranked[0].method, ranked[0].score, known)

        outcome = await verify_candidates(
            self._gateway, surface, entity_type.value, ranked[:2], context=context
        )
        if outcome.degraded or outcome.entity_id is None:
            return EntityResolution(
                query=surface,
                normalized=canonical_key,
                resolved=None,
                confidence=ranked[0].score,
                method=METHOD_LLM if not outcome.degraded else ranked[0].method,
                candidates=ranked,
                needs_verification=True,
                explanation=f"Top candidates are within {AMBIGUITY_MARGIN:.2f}; {outcome.reason}.",
            )
        chosen = [candidate for candidate in ranked if candidate.entity_id == outcome.entity_id]
        return self._resolution(
            surface, canonical_key, chosen + ranked, METHOD_LLM, outcome.confidence, known, note=outcome.reason
        )

    # -- assembly ---------------------------------------------------------
    def _resolution(
        self,
        surface: str,
        canonical_key: str,
        candidates: Sequence[ResolutionCandidate],
        method: str,
        confidence: float,
        known: Mapping[str, CanonicalEntity],
        *,
        note: str = "",
    ) -> EntityResolution:
        ranked = _rank(candidates)
        winner = known.get(ranked[0].entity_id) if ranked else None
        explanation = _explain(surface, canonical_key, method, ranked, note)
        log.debug("entity.resolved", surface=surface, method=method, confidence=confidence)
        return EntityResolution(
            query=surface,
            normalized=canonical_key,
            resolved=winner,
            confidence=confidence if winner is not None else 0.0,
            method=method if winner is not None else METHOD_NONE,
            candidates=ranked,
            needs_verification=winner is None,
            explanation=explanation,
        )


# ---------------------------------------------------------------------------
# Module-level helpers (pure).
# ---------------------------------------------------------------------------
def _candidate(
    entity: CanonicalEntity,
    score: float,
    method: str,
    rationale: str,
    known: dict[str, CanonicalEntity],
) -> ResolutionCandidate:
    known[entity.entity_id] = entity
    return ResolutionCandidate(
        entity_id=entity.entity_id,
        canonical_name=entity.canonical_name,
        entity_type=entity.entity_type,
        score=round(float(score), 4),
        method=method,
        rationale=rationale,
    )


def _rank(candidates: Sequence[ResolutionCandidate]) -> list[ResolutionCandidate]:
    """Highest score first, de-duplicated by entity id (best row wins)."""
    best: dict[str, ResolutionCandidate] = {}
    for candidate in candidates:
        current = best.get(candidate.entity_id)
        if current is None or candidate.score > current.score:
            best[candidate.entity_id] = candidate
    return sorted(best.values(), key=lambda item: (-item.score, item.entity_id))


def _decisive(
    candidates: Sequence[ResolutionCandidate], threshold: float, method: str
) -> ResolutionCandidate | None:
    ranked = [candidate for candidate in _rank(candidates) if candidate.method == method]
    if not ranked or ranked[0].score < threshold:
        return None
    runner_up = [c for c in _rank(candidates) if c.entity_id != ranked[0].entity_id]
    if runner_up and (ranked[0].score - runner_up[0].score) <= AMBIGUITY_MARGIN:
        return None
    return ranked[0]


def _type_compatible(entity: CanonicalEntity, entity_type: EntityType) -> bool:
    return entity_type is EntityType.OTHER or entity.entity_type is entity_type


def _looks_like_single_name(surface: str) -> bool:
    token = surface.strip()
    return bool(token) and token[:1].isupper() and token.isalpha() and len(token) >= 3


def _explain(
    surface: str, canonical_key: str, method: str, ranked: Sequence[ResolutionCandidate], note: str
) -> str:
    if not ranked:
        return f"{surface!r} normalised to {canonical_key!r}; no candidate found."
    head = ranked[0]
    parts = [
        f"{surface!r} normalised to {canonical_key!r}",
        f"matched {head.canonical_name} ({head.entity_id}) via {method} at {head.score:.3f}",
    ]
    if head.rationale:
        parts.append(head.rationale)
    if len(ranked) > 1:
        parts.append(f"runner-up {ranked[1].canonical_name} at {ranked[1].score:.3f}")
    if note:
        parts.append(note)
    return "; ".join(parts) + "."
