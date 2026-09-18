"""Adapters between service contracts that are deliberately different shapes.

`spectra_ingestion` wants a minimal positional mention tuple so it has no
dependency on the entity-resolution package.  `spectra_entity_resolution`
produces a rich `EntityMention`.  Both are right for their own purpose, so the
translation lives here in the integration layer rather than forcing either side
to know about the other.
"""

from __future__ import annotations

from typing import Any

from spectra_config.logging import get_logger
from spectra_schemas import EntityType, Modality

log = get_logger(__name__)

# `spectra_ingestion.entity_hook.Mention`
MentionTuple = tuple[str, EntityType, int, int]


class IngestionEntityExtractor:
    """Presents the entity resolver through `spectra_ingestion`'s protocol.

    Satisfies ``extract(text, modality) -> list[tuple[surface, type, start, end]]``
    while delegating the actual recognition to the resolution service, so
    ingestion and investigation agree on what an entity is.
    """

    def __init__(self, extractor: Any) -> None:
        self._extractor = extractor

    def extract(self, text: str, modality: Modality) -> list[MentionTuple]:
        mentions = self._extractor.extract(text, modality)
        out: list[MentionTuple] = []
        for mention in mentions:
            surface = getattr(mention, "surface", None)
            entity_type = getattr(mention, "entity_type", None)
            start = getattr(mention, "char_start", None)
            end = getattr(mention, "char_end", None)
            if not surface or entity_type is None:
                continue
            # Offsets are optional upstream but required for provenance here;
            # recover them rather than dropping an otherwise valid mention.
            if start is None or end is None:
                start = text.find(surface)
                if start < 0:
                    continue
                end = start + len(surface)
            out.append((surface, entity_type, int(start), int(end)))
        return out


def ingestion_extractor_for(entities_service: Any) -> IngestionEntityExtractor | None:
    """Build the adapter, or return None when entity resolution is unavailable."""
    extractor = getattr(entities_service, "extractor", None)
    if extractor is None:
        return None
    return IngestionEntityExtractor(extractor)
