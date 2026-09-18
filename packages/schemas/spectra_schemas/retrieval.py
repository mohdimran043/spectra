"""Search request / response contracts and the unified scoring breakdown."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .enums import Modality, SearchMode
from .provenance import Provenance


class SearchFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_ids: list[str] = Field(default_factory=list)
    modalities: list[Modality] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    occurred_after: datetime | None = None
    occurred_before: datetime | None = None
    media_types: list[str] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not any(
            [
                self.source_ids,
                self.modalities,
                self.asset_ids,
                self.entity_ids,
                self.occurred_after,
                self.occurred_before,
                self.media_types,
            ]
        )


class ScoreBreakdown(BaseModel):
    """Every ranking signal, kept separate so ranking stays inspectable.

    Ranking is deliberately *not* raw cosine similarity - see docs/search-architecture.md.
    """

    model_config = ConfigDict(extra="forbid")

    lexical: float = 0.0
    semantic: float = 0.0
    rerank: float | None = None
    entity_match: float = 0.0
    metadata_match: float = 0.0
    source_reliability: float = 0.5
    freshness: float = 0.5
    final: float = 0.0

    def explain(self) -> str:
        parts = [
            f"lexical={self.lexical:.3f}",
            f"semantic={self.semantic:.3f}",
            f"entity={self.entity_match:.3f}",
            f"meta={self.metadata_match:.3f}",
            f"reliability={self.source_reliability:.3f}",
            f"freshness={self.freshness:.3f}",
        ]
        if self.rerank is not None:
            parts.append(f"rerank={self.rerank:.3f}")
        return ", ".join(parts)


class SearchHit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    asset_id: str
    source_id: str
    modality: Modality
    title: str | None = None
    snippet: str = ""
    text: str = ""
    score: float = 0.0
    scores: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    provenance: Provenance
    entities: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime | None = None


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = ""
    mode: SearchMode = SearchMode.FAST
    filters: SearchFilters = Field(default_factory=SearchFilters)
    top_k: int = 20
    image_asset_id: str | None = Field(default=None, description="Image-to-anything search")
    include_text: bool = False
    rerank: bool = True


class RetrievalStageStat(BaseModel):
    stage: str
    candidates_in: int = 0
    candidates_out: int = 0
    latency_ms: float = 0.0
    detail: str | None = None


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    mode: SearchMode
    hits: list[SearchHit] = Field(default_factory=list)
    total_candidates: int = 0
    stages: list[RetrievalStageStat] = Field(default_factory=list)
    latency_ms: float = 0.0
    degraded: bool = False
    degraded_reasons: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
