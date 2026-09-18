"""Investigation state, agent trace and the structured answer contract."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .enums import (
    AgentName,
    AnswerStatus,
    ClaimStatus,
    ConfidenceLabel,
    InvestigationStatus,
    Modality,
    QueryIntent,
    SearchMode,
    TraceStatus,
)
from .evidence import (
    ApplicationLink,
    Claim,
    Contradiction,
    EvidenceLedger,
    TimelineEvent,
    VerificationResult,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TraceStep(BaseModel):
    """One observable action.  Action summaries only - never model chain-of-thought."""

    model_config = ConfigDict(extra="forbid")

    step_id: str
    investigation_id: str
    sequence: int
    agent: AgentName
    tool: str | None = None
    status: TraceStatus = TraceStatus.STARTED
    title: str = ""
    input_summary: str = ""
    output_summary: str = ""
    started_at: datetime = Field(default_factory=_now)
    completed_at: datetime | None = None
    latency_ms: float = 0.0
    evidence_ids: list[str] = Field(default_factory=list)
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=_now)
    completed_at: datetime | None = None
    latency_ms: float = 0.0
    ok: bool = True
    error: str | None = None
    result_summary: str = ""
    result_count: int = 0


class BudgetState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: SearchMode = SearchMode.DEEP
    max_tool_calls: int = 30
    max_latency_seconds: float = 60.0
    max_iterations: int = 8
    tool_calls_used: int = 0
    iterations_used: int = 0
    elapsed_seconds: float = 0.0
    exhausted_reason: str | None = None

    @property
    def tool_calls_remaining(self) -> int:
        return max(self.max_tool_calls - self.tool_calls_used, 0)

    def is_exhausted(self) -> bool:
        return (
            self.tool_calls_used >= self.max_tool_calls
            or self.iterations_used >= self.max_iterations
            or self.elapsed_seconds >= self.max_latency_seconds
        )


class QueryUnderstanding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original: str
    rewritten: str = ""
    intent: QueryIntent = QueryIntent.SEMANTIC_SEARCH
    complexity: str = "simple"
    detected_ids: list[str] = Field(default_factory=list)
    target_modalities: list[Modality] = Field(default_factory=list)
    temporal_hint: str | None = None
    keywords: list[str] = Field(default_factory=list)
    explanation: str = ""
    produced_by: str = "rule-router"


class AgentAvailability(BaseModel):
    name: str
    enabled: bool
    ready: bool
    reason: str | None = None
    alternatives: list[str] = Field(default_factory=list)


class InvestigationMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    total_latency_ms: float = 0.0
    tool_calls: int = 0
    iterations: int = 0
    candidates_retrieved: int = 0
    evidence_used: int = 0
    evidence_rejected: int = 0
    contradictions: int = 0
    claims_made: int = 0
    claims_refuted: int = 0
    model_latency_ms: dict[str, float] = Field(default_factory=dict)
    models_used: list[str] = Field(default_factory=list)
    stage_latency_ms: dict[str, float] = Field(default_factory=dict)
    gpu_peak_mb: float | None = None
    tokens: dict[str, int] = Field(default_factory=dict)
    sources_considered: list[str] = Field(default_factory=list)


class InvestigationState(BaseModel):
    """Serialisable state of one investigation - the agent's whole memory."""

    model_config = ConfigDict(extra="forbid")

    investigation_id: str
    case_id: str | None = None
    goal: str
    mode: SearchMode = SearchMode.DEEP
    status: InvestigationStatus = InvestigationStatus.CREATED
    understanding: QueryUnderstanding | None = None
    plan: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    evidence: EvidenceLedger = Field(default_factory=EvidenceLedger)
    contradictions: list[Contradiction] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    verification: VerificationResult | None = None
    tool_history: list[ToolInvocation] = Field(default_factory=list)
    trace: list[TraceStep] = Field(default_factory=list)
    budget: BudgetState = Field(default_factory=BudgetState)
    confidence: float = 0.0
    answer: str = ""
    answer_status: AnswerStatus = AnswerStatus.INSUFFICIENT_EVIDENCE
    application_links: list[ApplicationLink] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    metrics: InvestigationMetrics = Field(default_factory=InvestigationMetrics)
    degraded: bool = False
    degraded_reasons: list[str] = Field(default_factory=list)
    agent_availability: list[AgentAvailability] = Field(default_factory=list)
    uploaded_asset_ids: list[str] = Field(default_factory=list)
    followups: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    user_id: str | None = None
    role: str = "analyst"

    @property
    def confidence_label(self) -> ConfidenceLabel:
        return ConfidenceLabel.from_score(self.confidence)

    def leading_claim(self) -> Claim | None:
        """The best-supported claim - what the answer is built around."""
        live = [c for c in self.claims if c.status is not ClaimStatus.REFUTED]
        return max(live, key=lambda c: c.confidence, default=None)


class QueryExplanation(BaseModel):
    """User-facing 'why SPECTRA searched these sources'."""

    reasons: list[str] = Field(default_factory=list)
    sources_selected: list[str] = Field(default_factory=list)
    sources_skipped: list[dict[str, str]] = Field(default_factory=list)


class SearchAutopsy(BaseModel):
    """Post-investigation forensics - the demonstration centrepiece."""

    model_config = ConfigDict(extra="forbid")

    investigation_id: str
    sources_considered: list[str] = Field(default_factory=list)
    candidates_retrieved: int = 0
    evidence_used: int = 0
    evidence_rejected: int = 0
    rejection_reasons: dict[str, int] = Field(default_factory=dict)
    tool_calls: int = 0
    tool_breakdown: dict[str, int] = Field(default_factory=dict)
    contradictions: int = 0
    total_latency_ms: float = 0.0
    stage_latency_ms: dict[str, float] = Field(default_factory=dict)
    models_used: list[str] = Field(default_factory=list)
    gpu_peak_mb: float | None = None
    claims_made: int = 0
    claims_refuted: int = 0
    evidence_diversity: float = 0.0
    degraded: bool = False
    degraded_reasons: list[str] = Field(default_factory=list)


class InvestigationAnswer(BaseModel):
    """The structured response contract.

    The application NEVER parses free-form model text for behaviour - it reads
    these fields.
    """

    model_config = ConfigDict(extra="forbid")

    investigation_id: str
    answer: str
    confidence: float
    confidence_label: ConfidenceLabel
    status: AnswerStatus
    entities: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    application_links: list[ApplicationLink] = Field(default_factory=list)
    explanation: QueryExplanation = Field(default_factory=QueryExplanation)
    autopsy: SearchAutopsy | None = None
    metrics: InvestigationMetrics = Field(default_factory=InvestigationMetrics)
    degraded: bool = False
    degraded_reasons: list[str] = Field(default_factory=list)
    followups: list[str] = Field(default_factory=list)


class InvestigationCase(BaseModel):
    """Persistent case that can be reopened and continued."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    title: str
    question: str
    investigation_ids: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    status: InvestigationStatus = InvestigationStatus.CREATED
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    evidence_count: int = 0
    contradiction_count: int = 0
    claim_count: int = 0
    confidence: float = 0.0
