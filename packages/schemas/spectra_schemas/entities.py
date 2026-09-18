"""Entity mentions, canonical entities and cross-modal resolution results."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .enums import EntityType, Modality


def _now() -> datetime:
    return datetime.now(timezone.utc)


class EntityMention(BaseModel):
    """A surface form observed in one specific place."""

    model_config = ConfigDict(extra="forbid")

    mention_id: str
    surface: str
    normalized: str
    entity_type: EntityType
    modality: Modality
    chunk_id: str | None = None
    asset_id: str | None = None
    source_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    extractor: str = "pattern"
    confidence: float = 1.0
    canonical_id: str | None = None


class CanonicalEntity(BaseModel):
    """The resolved identity that many mentions collapse onto."""

    model_config = ConfigDict(extra="forbid")

    entity_id: str
    entity_type: EntityType
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    normalized_keys: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    source_ids: list[str] = Field(default_factory=list)
    modalities: list[Modality] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    mention_count: int = 0
    first_seen: datetime = Field(default_factory=_now)
    last_seen: datetime = Field(default_factory=_now)


class ResolutionCandidate(BaseModel):
    entity_id: str
    canonical_name: str
    entity_type: EntityType
    score: float
    method: str = Field(description="exact | normalized | fuzzy | semantic | database | llm")
    rationale: str | None = None


class EntityResolution(BaseModel):
    """Auditable output of the resolution cascade for one surface form."""

    model_config = ConfigDict(extra="forbid")

    query: str
    normalized: str
    resolved: CanonicalEntity | None = None
    confidence: float = 0.0
    method: str = "none"
    candidates: list[ResolutionCandidate] = Field(default_factory=list)
    needs_verification: bool = False
    explanation: str = ""


class EntityLink(BaseModel):
    """A ``chunk REFERS_TO entity`` edge, produced during ingestion."""

    entity_id: str
    chunk_id: str
    asset_id: str
    source_id: str
    modality: Modality
    surface: str
    confidence: float = 1.0
