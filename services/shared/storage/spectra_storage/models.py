"""SQLAlchemy 2.0 ORM models for the SPECTRA control plane.

Scalar fields that the system actually queries on become real, indexed columns;
nested pydantic structures (provenance, metrics, evidence ledgers) are stored as
JSON so a schema addition upstream cannot silently truncate stored state.  All
timestamps go through ``UtcDateTime`` because SQLite forgets timezones, and an
investigation whose ``occurred_at`` drifts by the local UTC offset would corrupt
every timeline it appears in.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# ``metadata`` is reserved by DeclarativeBase, so the pydantic ``metadata`` field is
# stored in a ``metadata_json`` column - attribute and column names stay identical,
# which keeps ON CONFLICT upserts and hand-written SQL in agreement.
ID_LENGTH = 128
KEY_LENGTH = 256
NAME_LENGTH = 512
SHORT_LENGTH = 64
URI_LENGTH = 1024


class UtcDateTime(TypeDecorator):
    """Timezone-preserving datetime that behaves the same on SQLite and Postgres."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base for every control-plane table."""


class SourceRow(Base):
    __tablename__ = "sources"

    source_id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    name: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    type: Mapped[str] = mapped_column(String(SHORT_LENGTH), nullable=False, index=True)
    modalities: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    connection: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    credential_ref: Mapped[str | None] = mapped_column(String(KEY_LENGTH), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reliability_override: Mapped[float | None] = mapped_column(Float, nullable=True)
    reliability_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    permissions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    last_sync: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    record_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    asset_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(SHORT_LENGTH), default="unconfigured", nullable=False)
    status_detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class AssetRow(Base):
    __tablename__ = "assets"

    asset_id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(SHORT_LENGTH), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    object_uri: Mapped[str] = mapped_column(String(URI_LENGTH), nullable=False)
    media_type: Mapped[str] = mapped_column(String(SHORT_LENGTH), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(KEY_LENGTH), default="", nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(SHORT_LENGTH), default="1", nullable=False)
    version_status: Mapped[str] = mapped_column(String(SHORT_LENGTH), default="current", nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    modified_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    ingested_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(SHORT_LENGTH), default="queued", nullable=False, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    permissions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)


class ChunkRow(Base):
    __tablename__ = "chunks"
    __table_args__ = (Index("chunks_asset_ordinal", "asset_id", "ordinal"),)

    chunk_id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False, index=True)
    modality: Mapped[str] = mapped_column(String(SHORT_LENGTH), nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(String(NAME_LENGTH), nullable=True)
    ordinal: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    entities: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    index_version: Mapped[str | None] = mapped_column(String(SHORT_LENGTH), nullable=True, index=True)
    embedding_ref: Mapped[str | None] = mapped_column(String(KEY_LENGTH), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    occurred_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True, index=True)
    permissions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)


class EntityRow(Base):
    __tablename__ = "entities"

    entity_id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(SHORT_LENGTH), nullable=False, index=True)
    canonical_name: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False, index=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    normalized_keys: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    source_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    modalities: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    mention_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    first_seen: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    last_seen: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class EntityKeyRow(Base):
    """Denormalised ``normalized_keys`` so key lookup is an indexed equality scan."""

    __tablename__ = "entity_keys"

    normalized_key: Mapped[str] = mapped_column(String(KEY_LENGTH), primary_key=True, index=True)
    entity_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("entities.entity_id", ondelete="CASCADE"), primary_key=True
    )


class EntityLinkRow(Base):
    __tablename__ = "entity_links"

    entity_id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, index=True)
    chunk_id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, index=True)
    asset_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False, index=True)
    modality: Mapped[str] = mapped_column(String(SHORT_LENGTH), nullable=False)
    surface: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)


class IngestJobRow(Base):
    __tablename__ = "ingest_jobs"

    job_id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    asset_id: Mapped[str | None] = mapped_column(String(ID_LENGTH), nullable=True, index=True)
    source_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(SHORT_LENGTH), default="queued", nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(SHORT_LENGTH), default="queued", nullable=False)
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    stages_completed: Mapped[list] = mapped_column(JSON, default=list, nullable=False)


class InvestigationRow(Base):
    """Indexed header columns plus the complete serialised ``InvestigationState``."""

    __tablename__ = "investigations"

    investigation_id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    case_id: Mapped[str | None] = mapped_column(String(ID_LENGTH), nullable=True, index=True)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(SHORT_LENGTH), default="deep", nullable=False)
    status: Mapped[str] = mapped_column(String(SHORT_LENGTH), default="created", nullable=False, index=True)
    answer_status: Mapped[str] = mapped_column(String(SHORT_LENGTH), default="insufficient_evidence", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(ID_LENGTH), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    state: Mapped[dict] = mapped_column(JSON, nullable=False)


class InvestigationCaseRow(Base):
    __tablename__ = "investigation_cases"

    case_id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    title: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    investigation_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    entity_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(SHORT_LENGTH), default="created", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    contradiction_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    claim_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


class TraceStepRow(Base):
    __tablename__ = "trace_steps"
    __table_args__ = (Index("trace_steps_investigation_sequence", "investigation_id", "sequence"),)

    step_id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True)
    investigation_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    agent: Mapped[str] = mapped_column(String(SHORT_LENGTH), nullable=False)
    tool: Mapped[str | None] = mapped_column(String(NAME_LENGTH), nullable=True)
    status: Mapped[str] = mapped_column(String(SHORT_LENGTH), default="started", nullable=False)
    title: Mapped[str] = mapped_column(String(NAME_LENGTH), default="", nullable=False)
    input_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    output_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class IndexVersionRow(Base):
    __tablename__ = "index_versions"

    index_version: Mapped[str] = mapped_column(String(SHORT_LENGTH), primary_key=True)
    embedding_model: Mapped[str] = mapped_column(String(NAME_LENGTH), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    parser_version: Mapped[str] = mapped_column(String(SHORT_LENGTH), nullable=False)
    vision_model: Mapped[str | None] = mapped_column(String(NAME_LENGTH), nullable=True)
    speech_model: Mapped[str | None] = mapped_column(String(NAME_LENGTH), nullable=True)
    ocr_engine: Mapped[str | None] = mapped_column(String(NAME_LENGTH), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)


class SqlAuditRow(Base):
    """Every generated SQL statement, kept for the audit trail and the autopsy view."""

    __tablename__ = "sql_audit"

    audit_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False, index=True)
    sql: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    user_id: Mapped[str] = mapped_column(String(ID_LENGTH), nullable=False, index=True)
    rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
