"""Source registry, asset catalog and index-version records."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .enums import AssetKind, JobStatus, Modality, SearchMode, SourceStatus, SourceType


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SourceDescriptor(BaseModel):
    """One configured place SPECTRA may read from."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    name: str
    type: SourceType
    modalities: list[Modality] = Field(default_factory=list)
    connection: dict[str, Any] = Field(default_factory=dict, description="Secrets are never stored here")
    credential_ref: str | None = Field(default=None, description="Pointer into the secret store")
    enabled: bool = True
    reliability_override: float | None = None
    reliability_reason: str | None = None
    permissions: list[str] = Field(default_factory=lambda: ["admin", "analyst", "viewer"])
    created_at: datetime = Field(default_factory=_now)
    last_sync: datetime | None = None
    record_count: int = 0
    asset_count: int = 0
    status: SourceStatus = SourceStatus.UNCONFIGURED
    status_detail: str | None = None


class SourceHealth(BaseModel):
    source_id: str
    status: SourceStatus
    detail: str | None = None
    checked_at: datetime = Field(default_factory=_now)
    latency_ms: float | None = None
    asset_count: int = 0
    record_count: int = 0


class Asset(BaseModel):
    """A single ingested object (file, image, video, audio, table export)."""

    model_config = ConfigDict(extra="forbid")

    asset_id: str
    source_id: str
    kind: AssetKind
    title: str
    object_uri: str
    media_type: str
    size_bytes: int = 0
    content_hash: str = ""
    version: str = "1"
    version_status: str = "current"
    created_at: datetime = Field(default_factory=_now)
    modified_at: datetime | None = None
    ingested_at: datetime | None = None
    status: JobStatus = JobStatus.QUEUED
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    duration_seconds: float | None = None
    page_count: int | None = None
    permissions: list[str] = Field(default_factory=lambda: ["admin", "analyst", "viewer"])

    @property
    def modality(self) -> Modality:
        return {
            AssetKind.DOCUMENT: Modality.DOCUMENT,
            AssetKind.IMAGE: Modality.IMAGE,
            AssetKind.VIDEO: Modality.VIDEO,
            AssetKind.AUDIO: Modality.AUDIO,
            AssetKind.TABLE: Modality.DATABASE,
        }[self.kind]


class IngestJob(BaseModel):
    job_id: str
    asset_id: str | None = None
    source_id: str
    status: JobStatus = JobStatus.QUEUED
    stage: str = "queued"
    progress: float = 0.0
    message: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    stages_completed: list[str] = Field(default_factory=list)


class SearchHistoryEntry(BaseModel):
    """One search someone actually ran.

    Recorded after the fact and never read back into retrieval, so a slow or
    failed write can never change what a search returns. It exists so an
    operator can see what has been asked, what came back, and re-run it.
    """

    model_config = ConfigDict(extra="forbid")

    search_id: str
    query: str
    mode: SearchMode = SearchMode.FAST
    result_count: int = 0
    candidates_screened: int = 0
    latency_ms: float = 0.0
    source_ids: list[str] = Field(default_factory=list)
    answered: bool = False
    user_id: str | None = None
    searched_at: datetime = Field(default_factory=_now)

    @property
    def found_nothing(self) -> bool:
        """An empty result set is a real outcome, and worth seeing in the list."""
        return self.result_count == 0


class IndexVersion(BaseModel):
    """Recorded on every chunk so models can change without destroying the index."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    index_version: str
    embedding_model: str
    embedding_dimension: int
    parser_version: str
    vision_model: str | None = None
    speech_model: str | None = None
    ocr_engine: str | None = None
    created_at: datetime = Field(default_factory=_now)

    def key(self) -> str:
        return f"{self.index_version}:{self.embedding_model}:{self.embedding_dimension}"


class Chunk(BaseModel):
    """The atomic retrievable unit: a text span with full provenance.

    Documents, transcripts, OCR output, scene descriptions and serialised
    database rows all become chunks, which is what makes cross-modal retrieval
    a single code path rather than five.
    """

    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    asset_id: str
    source_id: str
    modality: Modality
    text: str
    title: str | None = None
    ordinal: int = 0
    provenance: dict[str, Any] = Field(default_factory=dict)
    entities: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    index_version: str | None = None
    embedding_ref: str | None = None
    created_at: datetime = Field(default_factory=_now)
    occurred_at: datetime | None = Field(
        default=None, description="When the described event happened (drives the timeline)"
    )
    permissions: list[str] = Field(default_factory=lambda: ["admin", "analyst", "viewer"])
