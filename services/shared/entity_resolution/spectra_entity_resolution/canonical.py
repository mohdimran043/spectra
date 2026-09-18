"""Construction and immutable extension of :class:`CanonicalEntity` records.

Separated from the cascade so the "what does an entity look like" rules live in
one small, purely functional module.  Nothing here performs I/O and nothing here
mutates its input: every update returns a new model via ``model_copy``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from spectra_schemas import CanonicalEntity, EntityMention, EntityType, Modality
from spectra_schemas.ids import entity_id as make_entity_id

from .normalize import normalize_surface, person_keys

#: Confidence assigned to an entity materialised from a system-of-record row.
#: Kept in step with ``resolver.DATABASE_CONFIDENCE``.
DATABASE_ROW_CONFIDENCE = 0.97


def now() -> datetime:
    return datetime.now(timezone.utc)


def keys_for_mention(mention: EntityMention) -> tuple[str, ...]:
    """Every normalised key under which this mention's entity is findable."""
    if mention.entity_type is EntityType.PERSON:
        return person_keys(mention.surface).all_keys()
    return (normalize_surface(mention.surface, mention.entity_type),)


def mention_key(mention: EntityMention) -> str:
    return f"{mention.entity_type.value}:{mention.normalized}"


def canonical_name_for(mention: EntityMention) -> str:
    if mention.entity_type is EntityType.PERSON:
        return person_keys(mention.surface).display
    return normalize_surface(mention.surface, mention.entity_type) or mention.surface


def create_entity(mention: EntityMention) -> CanonicalEntity:
    keys = keys_for_mention(mention)
    return CanonicalEntity(
        entity_id=make_entity_id(mention.entity_type.value, keys[0]),
        entity_type=mention.entity_type,
        canonical_name=canonical_name_for(mention),
        aliases=[mention.surface],
        normalized_keys=list(keys),
        confidence=mention.confidence,
        source_ids=[mention.source_id] if mention.source_id else [],
        modalities=[mention.modality],
        mention_count=1,
    )


def extend_entity(entity: CanonicalEntity, mention: EntityMention) -> CanonicalEntity:
    """Return a NEW entity carrying this mention's alias, keys, source and modality."""
    return entity.model_copy(
        update={
            "aliases": merge_unique(entity.aliases, [mention.surface]),
            "normalized_keys": merge_unique(entity.normalized_keys, list(keys_for_mention(mention))),
            "source_ids": merge_unique(entity.source_ids, [mention.source_id] if mention.source_id else []),
            "modalities": merge_unique(entity.modalities, [mention.modality]),
            "confidence": max(entity.confidence, mention.confidence),
            "mention_count": entity.mention_count + 1,
            "last_seen": now(),
        }
    )


def entity_from_row(entity_type: EntityType, value: str, row: Mapping[str, Any]) -> CanonicalEntity:
    """Materialise a canonical entity from a system-of-record row."""
    name = str(row.get("name") or row.get("canonical_name") or value)
    return CanonicalEntity(
        entity_id=make_entity_id(entity_type.value, value),
        entity_type=entity_type,
        canonical_name=value,
        aliases=[name] if name != value else [],
        normalized_keys=[value],
        confidence=DATABASE_ROW_CONFIDENCE,
        source_ids=[str(row["source_id"])] if row.get("source_id") else [],
        modalities=[Modality.DATABASE],
        attributes=dict(row),
        mention_count=1,
    )


def merge_unique(existing: Sequence[Any], additions: Sequence[Any]) -> list[Any]:
    """Order-preserving union - never mutates ``existing``."""
    merged = list(existing)
    merged.extend(item for item in additions if item not in merged)
    return merged
