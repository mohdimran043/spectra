"""Evidence ledger, claims, contradictions, timeline and verification."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .enums import (
    ClaimStatus,
    ConfidenceLabel,
    EntityType,
    EvidenceKind,
    EvidenceStance,
    Modality,
)
from .provenance import Provenance


def _now() -> datetime:
    return datetime.now(timezone.utc)


class EvidenceItem(BaseModel):
    """One citable fact with its full provenance and reliability accounting.

    Nothing reaches the user as fact without a corresponding EvidenceItem.
    """

    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    kind: EvidenceKind
    modality: Modality
    summary: str = Field(description="Short extractive statement of what this evidence shows")
    excerpt: str = ""
    provenance: Provenance
    stance: EvidenceStance = EvidenceStance.NEUTRAL
    relevance: float = 0.0
    reliability: float = 0.5
    reliability_reason: str = ""
    entities: list[str] = Field(default_factory=list)
    occurred_at: datetime | None = None
    retrieved_at: datetime = Field(default_factory=_now)
    retrieved_by: str = ""
    claim_ids: list[str] = Field(default_factory=list)

    @property
    def weight(self) -> float:
        """Combined usefulness: how relevant AND how trustworthy."""
        return round(self.relevance * self.reliability, 6)

    def citation(self) -> str:
        return self.provenance.human()


class EvidenceLedger(BaseModel):
    """Append-only record of everything considered, used and rejected."""

    model_config = ConfigDict(extra="forbid")

    items: list[EvidenceItem] = Field(default_factory=list)
    rejected_count: int = 0
    considered_count: int = 0
    rejection_reasons: dict[str, int] = Field(default_factory=dict)

    def with_items(self, new_items: list[EvidenceItem]) -> EvidenceLedger:
        """Return a new ledger - ledgers are never mutated in place."""
        known = {i.evidence_id for i in self.items}
        merged = list(self.items) + [i for i in new_items if i.evidence_id not in known]
        return EvidenceLedger(
            items=merged,
            rejected_count=self.rejected_count,
            considered_count=self.considered_count + len(new_items),
            rejection_reasons=dict(self.rejection_reasons),
        )

    def diversity(self) -> float:
        """Independent-corroboration score in [0,1].

        Three paragraphs of one PDF must not outrank a DB record + a PDF + a
        video, so diversity counts distinct sources AND distinct modalities.
        """
        if not self.items:
            return 0.0
        sources = {i.provenance.source_id for i in self.items}
        modalities = {i.modality for i in self.items}
        assets = {_asset_of(i) for i in self.items}
        source_term = min(len(sources) / 3.0, 1.0)
        modality_term = min(len(modalities) / 3.0, 1.0)
        asset_term = min(len(assets) / 4.0, 1.0)
        return round(0.4 * source_term + 0.4 * modality_term + 0.2 * asset_term, 4)

    def by_stance(self, stance: EvidenceStance) -> list[EvidenceItem]:
        return [i for i in self.items if i.stance is stance]


def _asset_of(item: EvidenceItem) -> str:
    loc = item.provenance.locator
    for attr in ("document_id", "image_id", "video_id", "audio_id", "record_id", "resource"):
        value = getattr(loc, attr, None)
        if value:
            return str(value)
    return item.evidence_id


class Contradiction(BaseModel):
    """Two pieces of evidence that cannot both be true."""

    model_config = ConfigDict(extra="forbid")

    contradiction_id: str
    statement: str
    evidence_a: str
    evidence_b: str
    kind: str = "value_conflict"
    detail: str = ""
    resolution: str | None = None
    resolved_in_favour_of: str | None = None
    severity: float = 0.5
    entity_id: str | None = None


class TimelineEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    occurred_at: datetime
    label: str
    detail: str = ""
    modality: Modality
    evidence_ids: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    source_id: str | None = None
    precision: str = "exact"


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str
    supported: bool
    confidence: float
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)
    diversity: float = 0.0
    note: str = ""
    checks: dict[str, bool] = Field(default_factory=dict)


class Claim(BaseModel):
    """A single asserted statement, judged on the evidence that backs it.

    Each claim stands or falls on its own evidence. There is no competition
    between rival explanations, so a well-supported conclusion keeps its
    confidence instead of having it divided among alternatives.
    """

    model_config = ConfigDict(extra="forbid")

    claim_id: str
    text: str
    confidence: float = 0.0
    status: ClaimStatus = ClaimStatus.INSUFFICIENT
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)
    disproof_probe: str | None = Field(
        default=None, description="What evidence would show this claim is wrong"
    )
    disproof_searched: bool = False
    verified: bool = False
    verification_note: str = ""
    rationale: str = ""

    @property
    def evidence_ids(self) -> list[str]:
        """Every piece of evidence bearing on this claim, either way."""
        return [*self.supporting_evidence, *self.contradicting_evidence]

    @property
    def confidence_label(self) -> ConfidenceLabel:
        return ConfidenceLabel.from_score(self.confidence)


class ApplicationLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str
    entity_type: EntityType
    label: str
    url: str
    record_id: str
    verified_in_database: bool = False


class GraphNode(BaseModel):
    node_id: str
    labels: list[str] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    edge_id: str
    type: str
    start: str
    end: str
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphView(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    truncated: bool = False
