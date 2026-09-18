"""Model runtime, GPU telemetry and agent status contracts."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from .enums import ModelRole, ModelState


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ModelCandidate(BaseModel):
    runtime: str
    model: str
    vram_mb: int = 0
    device: str = "auto"
    dimension: int | None = None
    compute_type: str | None = None
    available: bool | None = None
    unavailable_reason: str | None = None


class ModelInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: ModelRole
    enabled: bool = True
    purpose: str = ""
    state: ModelState = ModelState.REGISTERED
    active_runtime: str | None = None
    active_model: str | None = None
    device: str | None = None
    vram_mb: int = 0
    dimension: int | None = None
    candidates: list[ModelCandidate] = Field(default_factory=list)
    loaded_at: datetime | None = None
    last_used_at: datetime | None = None
    load_count: int = 0
    unload_count: int = 0
    call_count: int = 0
    error_count: int = 0
    total_latency_ms: float = 0.0
    last_error: str | None = None
    degraded: bool = False
    degraded_reason: str | None = None

    @property
    def avg_latency_ms(self) -> float:
        return round(self.total_latency_ms / self.call_count, 2) if self.call_count else 0.0


class GPUStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool = False
    name: str | None = None
    driver_version: str | None = None
    total_mb: float = 0.0
    used_mb: float = 0.0
    free_mb: float = 0.0
    utilisation_pct: float | None = None
    temperature_c: float | None = None
    budget_mb: float = 0.0
    detail: str | None = None


class ModelEvent(BaseModel):
    at: datetime = Field(default_factory=_now)
    role: ModelRole
    event: str
    detail: str = ""
    vram_mb: int = 0


class ModelRuntimeStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: str
    gpu: GPUStatus
    models: list[ModelInfo] = Field(default_factory=list)
    resident_roles: list[ModelRole] = Field(default_factory=list)
    queue_depth: int = 0
    active_role: ModelRole | None = None
    recent_events: list[ModelEvent] = Field(default_factory=list)
    degraded: bool = False
    degraded_reasons: list[str] = Field(default_factory=list)


class AgentStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    label: str
    enabled: bool
    ready: bool
    state: str = "ready"
    reason: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)


class HealthReport(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"
    deployment_mode: str = "development"
    #: One entry per checked component, each carrying at least a `status`.
    components: dict[str, dict] = Field(default_factory=dict)
    #: Which backend implements each store. Not a component - it has no health
    #: of its own - so it is reported alongside them rather than among them.
    backends: dict[str, str] = Field(default_factory=dict)
    degraded: bool = False
    checked_at: datetime = Field(default_factory=_now)
