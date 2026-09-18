"""Mention extraction: free text -> :class:`EntityMention` objects.

Three passes, cheapest first:

1. **Grammar pass** - every declared identifier / date / service pattern.
2. **Person pass** - capitalised token sequences plus honorific-introduced names.
3. **Context-window pass** - bare numbers that no grammar claimed are typed by a
   keyword within :data:`CONTEXT_WINDOW_CHARS`, at a deliberately lower
   confidence so a stronger reading of the same span always wins.

Overlapping spans are resolved once, at the end: highest confidence first, then
longest span.  Character offsets always refer to the *input* string so the UI can
highlight the exact source text.
"""

from __future__ import annotations

from dataclasses import dataclass

from spectra_config.logging import get_logger
from spectra_schemas import EntityMention, EntityType, Modality
from spectra_schemas.ids import mention_id

from .normalize import normalize_surface
from .patterns import (
    BARE_NUMBER,
    CONFIDENCE_CONTEXT_ID,
    CONFIDENCE_PERSON_FULL,
    CONFIDENCE_PERSON_HONORIFIC,
    CONFIDENCE_PERSON_INITIAL,
    CONTEXT_KEYWORDS,
    CONTEXT_WINDOW_CHARS,
    HONORIFICS,
    PERSON_HONORIFIC,
    PERSON_SEQUENCE,
    PERSON_STOPWORDS,
    iter_pattern_matches,
)

log = get_logger(__name__)

#: Extractor labels recorded on every mention (``EntityMention.extractor``).
EXTRACTOR_PATTERN = "pattern"
EXTRACTOR_PERSON = "person"
EXTRACTOR_CONTEXT = "context"

#: A person surface must contain at least this many characters of real letters;
#: shorter sequences are almost always acronyms or sentence-initial noise.
MIN_PERSON_CHARS = 3


@dataclass(frozen=True)
class _RawMention:
    surface: str
    entity_type: EntityType
    start: int
    end: int
    confidence: float
    extractor: str

    @property
    def length(self) -> int:
        return self.end - self.start


class EntityExtractor:
    """Stateless, deterministic mention extractor."""

    def __init__(self, *, context_window: int = CONTEXT_WINDOW_CHARS) -> None:
        self._context_window = context_window

    def extract(
        self,
        text: str,
        modality: Modality,
        *,
        chunk_id: str | None = None,
        asset_id: str | None = None,
        source_id: str | None = None,
    ) -> list[EntityMention]:
        """Extract every mention in ``text``, ordered by character offset."""
        if not text or not text.strip():
            return []
        raw = [*self._grammar_pass(text), *self._person_pass(text), *self._context_pass(text)]
        resolved = _resolve_overlaps(raw)
        mentions = [
            self._to_mention(item, modality, chunk_id=chunk_id, asset_id=asset_id, source_id=source_id)
            for item in resolved
        ]
        log.debug("entity.extract", chars=len(text), mentions=len(mentions), modality=modality.value)
        return mentions

    # -- passes -----------------------------------------------------------
    def _grammar_pass(self, text: str) -> list[_RawMention]:
        return [
            _RawMention(
                surface=match.surface,
                entity_type=match.pattern.entity_type,
                start=match.start,
                end=match.end,
                confidence=match.pattern.confidence,
                extractor=EXTRACTOR_PATTERN,
            )
            for match in iter_pattern_matches(text)
        ]

    def _person_pass(self, text: str) -> list[_RawMention]:
        found: list[_RawMention] = []
        for match in PERSON_HONORIFIC.finditer(text):
            surface = match.group(1)
            start = match.start(1)
            found.append(
                _RawMention(surface, EntityType.PERSON, start, start + len(surface),
                            CONFIDENCE_PERSON_HONORIFIC, EXTRACTOR_PERSON)
            )
        for match in PERSON_SEQUENCE.finditer(text):
            surface = match.group(0)
            if not _is_person_like(surface):
                continue
            confidence = CONFIDENCE_PERSON_INITIAL if "." in surface else CONFIDENCE_PERSON_FULL
            found.append(
                _RawMention(surface, EntityType.PERSON, match.start(), match.end(), confidence, EXTRACTOR_PERSON)
            )
        return found

    def _context_pass(self, text: str) -> list[_RawMention]:
        found: list[_RawMention] = []
        lowered = text.lower()
        for match in BARE_NUMBER.finditer(text):
            entity_type = self._type_from_context(lowered, match.start(), match.end())
            if entity_type is None:
                continue
            found.append(
                _RawMention(
                    surface=match.group(0),
                    entity_type=entity_type,
                    start=match.start(),
                    end=match.end(),
                    confidence=CONFIDENCE_CONTEXT_ID,
                    extractor=EXTRACTOR_CONTEXT,
                )
            )
        return found

    def _type_from_context(self, lowered: str, start: int, end: int) -> EntityType | None:
        """Type a bare number by the *closest* keyword, not merely a present one."""
        left = max(0, start - self._context_window)
        window = lowered[left : min(len(lowered), end + self._context_window)]
        pivot = (start - left, end - left)
        best: tuple[int, EntityType] | None = None
        for entity_type, keywords in CONTEXT_KEYWORDS.items():
            distance = _nearest_keyword_distance(window, keywords, pivot)
            if distance is not None and (best is None or distance < best[0]):
                best = (distance, entity_type)
        return None if best is None else best[1]

    # -- assembly ---------------------------------------------------------
    def _to_mention(
        self,
        raw: _RawMention,
        modality: Modality,
        *,
        chunk_id: str | None,
        asset_id: str | None,
        source_id: str | None,
    ) -> EntityMention:
        return EntityMention(
            mention_id=mention_id(chunk_id or "", raw.start, raw.surface),
            surface=raw.surface,
            normalized=normalize_surface(raw.surface, raw.entity_type),
            entity_type=raw.entity_type,
            modality=modality,
            chunk_id=chunk_id,
            asset_id=asset_id,
            source_id=source_id,
            char_start=raw.start,
            char_end=raw.end,
            extractor=raw.extractor,
            confidence=raw.confidence,
        )


def _nearest_keyword_distance(
    window: str, keywords: tuple[str, ...], pivot: tuple[int, int]
) -> int | None:
    """Character gap between the number and the nearest of ``keywords``."""
    number_start, number_end = pivot
    best: int | None = None
    for keyword in keywords:
        position = window.find(keyword)
        while position >= 0:
            distance = _gap(position, position + len(keyword), number_start, number_end)
            if best is None or distance < best:
                best = distance
            position = window.find(keyword, position + 1)
    return best


def _gap(keyword_start: int, keyword_end: int, number_start: int, number_end: int) -> int:
    if keyword_end <= number_start:
        return number_start - keyword_end
    if keyword_start >= number_end:
        return keyword_start - number_end
    return 0


def _is_person_like(surface: str) -> bool:
    """Reject capitalised sequences that are clearly not names."""
    tokens = [token.strip(".").casefold() for token in surface.split()]
    if len(surface.replace(".", "").replace(" ", "")) < MIN_PERSON_CHARS:
        return False
    meaningful = [token for token in tokens if token and token not in HONORIFICS]
    if not meaningful:
        return False
    return not any(token in PERSON_STOPWORDS for token in meaningful)


def _resolve_overlaps(raw: list[_RawMention]) -> list[_RawMention]:
    """Keep the strongest non-overlapping reading of each span."""
    ordered = sorted(raw, key=lambda item: (-item.confidence, -item.length, item.start))
    kept: list[_RawMention] = []
    for candidate in ordered:
        if any(candidate.start < other.end and other.start < candidate.end for other in kept):
            continue
        kept.append(candidate)
    return sorted(kept, key=lambda item: (item.start, item.end))
