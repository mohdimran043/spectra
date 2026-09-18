"""Entity extraction hook used during ingestion.

Ingestion only needs *mentions*: a surface form, a type and a character span.
Canonicalisation beyond a normalised key is the entity-resolution service's job,
so this module defines the seam (:class:`EntityExtractor`) and ships a
dependency-free regex implementation.  A richer extractor is injected through
the constructor of the pipelines - never imported here.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Final, Protocol, runtime_checkable

from spectra_config.logging import get_logger
from spectra_schemas import (
    CanonicalEntity,
    Chunk,
    EntityLink,
    EntityType,
    Modality,
    entity_id,
)

log = get_logger(__name__)

Mention = tuple[str, EntityType, int, int]

MAX_MENTIONS_PER_CHUNK: Final[int] = 64

CONFIDENCE_BY_TYPE: Final[dict[EntityType, float]] = {
    EntityType.TRANSACTION: 0.98,
    EntityType.CUSTOMER: 0.98,
    EntityType.INCIDENT: 0.98,
    EntityType.ASSET: 0.95,
    EntityType.EVENT: 0.80,
    EntityType.PERSON: 0.60,
}
DEFAULT_CONFIDENCE: Final[float] = 0.5

#: Enterprise identifier patterns, highest precedence first.
ID_PATTERNS: Final[tuple[tuple[re.Pattern[str], EntityType], ...]] = (
    (re.compile(r"\bTX\d+\b"), EntityType.TRANSACTION),
    (re.compile(r"\bINC\d+\b"), EntityType.INCIDENT),
    (re.compile(r"\bAST\d+\b"), EntityType.ASSET),
    (re.compile(r"\bDOC-\d+\b"), EntityType.ASSET),
    (re.compile(r"\bVID-\d+\b"), EntityType.ASSET),
    (re.compile(r"\bIMG-\d+\b"), EntityType.ASSET),
    (re.compile(r"\bC\d+\b"), EntityType.CUSTOMER),
)

TIME_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?)?\b"),
    re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b"),
)

PERSON_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b[A-Z][a-z]{1,20}(?:\s+[A-Z][a-z]{1,20}){1,2}\b"
)

#: Capitalised words that start sentences and would otherwise look like names.
PERSON_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "the", "this", "that", "these", "those", "a", "an", "and", "but", "for", "from",
        "in", "on", "at", "by", "with", "we", "they", "he", "she", "it", "our", "their",
        "page", "section", "figure", "table", "chapter", "appendix", "slide", "sheet",
        "when", "where", "while", "after", "before", "during", "however", "based",
        "incident", "transaction", "customer", "asset", "report", "summary", "document",
    }
)


@runtime_checkable
class EntityExtractor(Protocol):
    """Anything that can find entity mentions in a piece of text."""

    def extract(self, text: str, modality: Modality) -> list[Mention]: ...


class Guard(Protocol):
    """Extra acceptance test applied to a candidate surface form."""

    def __call__(self, surface: str) -> bool: ...


class RegexEntityExtractor:
    """Deterministic enterprise-ID / person / timestamp extractor."""

    name = "regex"

    def __init__(self, *, max_mentions: int = MAX_MENTIONS_PER_CHUNK) -> None:
        self._max_mentions = max_mentions

    def extract(self, text: str, modality: Modality) -> list[Mention]:  # noqa: ARG002 - stable seam
        if not text:
            return []
        claimed: list[tuple[int, int]] = []
        mentions: list[Mention] = []
        for pattern, entity_type in ID_PATTERNS:
            mentions.extend(self._collect(pattern, entity_type, text, claimed))
        for pattern in TIME_PATTERNS:
            mentions.extend(self._collect(pattern, EntityType.EVENT, text, claimed))
        mentions.extend(self._collect(PERSON_PATTERN, EntityType.PERSON, text, claimed, guard=_is_person))
        mentions.sort(key=lambda item: item[2])
        return mentions[: self._max_mentions]

    def _collect(
        self,
        pattern: re.Pattern[str],
        entity_type: EntityType,
        text: str,
        claimed: list[tuple[int, int]],
        guard: Guard | None = None,
    ) -> list[Mention]:
        found: list[Mention] = []
        for match in pattern.finditer(text):
            span = (match.start(), match.end())
            surface = match.group(0)
            if _overlaps(span, claimed) or (guard is not None and not guard(surface)):
                continue
            claimed.append(span)
            found.append((surface, entity_type, span[0], span[1]))
        return found


def normalise_surface(surface: str, entity_type: EntityType) -> str:
    """Key used to collapse spellings of the same entity."""
    collapsed = " ".join(surface.split())
    if entity_type in {EntityType.PERSON, EntityType.ORGANISATION, EntityType.LOCATION}:
        return collapsed.casefold()
    return collapsed.upper()


def annotate_chunks(
    chunks: Sequence[Chunk], extractor: EntityExtractor
) -> tuple[list[Chunk], list[CanonicalEntity], list[EntityLink]]:
    """Attach entity ids to chunks and build the entity / link records.

    Returns new chunk objects - the inputs are never mutated.
    """
    entities: dict[str, CanonicalEntity] = {}
    links: list[EntityLink] = []
    annotated: list[Chunk] = []

    for chunk in chunks:
        mentions = _safe_extract(extractor, chunk)
        chunk_entity_ids: list[str] = []
        for surface, entity_type, start, _end in mentions:
            normalized = normalise_surface(surface, entity_type)
            identifier = entity_id(entity_type.value, normalized)
            entities[identifier] = _merge_entity(
                entities.get(identifier), identifier, surface, normalized, entity_type, chunk
            )
            if identifier not in chunk_entity_ids:
                chunk_entity_ids.append(identifier)
            links.append(_link(identifier, chunk, surface, entity_type, start))
        annotated.append(chunk.model_copy(update={"entities": chunk_entity_ids}))
    return annotated, list(entities.values()), links


def _safe_extract(extractor: EntityExtractor, chunk: Chunk) -> list[Mention]:
    try:
        return list(extractor.extract(chunk.text, chunk.modality))
    except Exception as exc:  # a bad extractor must not fail the whole ingest
        log.warning("entities.extract_failed", chunk_id=chunk.chunk_id, error=str(exc))
        return []


def _merge_entity(
    existing: CanonicalEntity | None,
    identifier: str,
    surface: str,
    normalized: str,
    entity_type: EntityType,
    chunk: Chunk,
) -> CanonicalEntity:
    if existing is None:
        return CanonicalEntity(
            entity_id=identifier,
            entity_type=entity_type,
            canonical_name=surface,
            aliases=[surface],
            normalized_keys=[normalized],
            confidence=CONFIDENCE_BY_TYPE.get(entity_type, DEFAULT_CONFIDENCE),
            source_ids=[chunk.source_id],
            modalities=[chunk.modality],
            mention_count=1,
        )
    return existing.model_copy(
        update={
            "aliases": _extend(existing.aliases, surface),
            "source_ids": _extend(existing.source_ids, chunk.source_id),
            "modalities": _extend(existing.modalities, chunk.modality),
            "mention_count": existing.mention_count + 1,
        }
    )


def _link(identifier: str, chunk: Chunk, surface: str, entity_type: EntityType, start: int) -> EntityLink:
    return EntityLink(
        entity_id=identifier,
        chunk_id=chunk.chunk_id,
        asset_id=chunk.asset_id,
        source_id=chunk.source_id,
        modality=chunk.modality,
        surface=surface,
        confidence=CONFIDENCE_BY_TYPE.get(entity_type, DEFAULT_CONFIDENCE),
    )


def _extend(values: Iterable[object], value: object) -> list:
    current = list(values)
    return current if value in current else [*current, value]


def _overlaps(span: tuple[int, int], claimed: Sequence[tuple[int, int]]) -> bool:
    return any(span[0] < end and start < span[1] for start, end in claimed)


def _is_person(surface: str) -> bool:
    words = surface.split()
    if len(words) < 2:
        return False
    return not any(word.casefold() in PERSON_STOPWORDS for word in words)
