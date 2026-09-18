"""Closed vocabularies shared by every SPECTRA service."""

from __future__ import annotations

from enum import Enum


class Modality(str, Enum):
    DOCUMENT = "document"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DATABASE = "database"
    GRAPH = "graph"
    EXTERNAL = "external"


class SourceType(str, Enum):
    LOCAL_FOLDER = "local_folder"
    S3 = "s3"
    POSTGRES = "postgres"
    MYSQL = "mysql"
    SQLITE = "sqlite"
    REST_API = "rest_api"
    UPLOAD = "upload"


class SourceStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNREACHABLE = "unreachable"
    UNCONFIGURED = "unconfigured"


class AssetKind(str, Enum):
    DOCUMENT = "document"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    TABLE = "table"


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    EXTRACTING = "extracting"
    EMBEDDING = "embedding"
    INDEXED = "indexed"
    READY = "ready"
    FAILED = "failed"


class EntityType(str, Enum):
    PERSON = "person"
    CUSTOMER = "customer"
    TRANSACTION = "transaction"
    INCIDENT = "incident"
    ASSET = "asset"
    SERVICE = "service"
    ORGANISATION = "organisation"
    LOCATION = "location"
    EVENT = "event"
    OTHER = "other"


class EvidenceKind(str, Enum):
    DOCUMENT = "document"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DATABASE = "database"
    APPLICATION_RECORD = "application_record"
    EXTERNAL_API = "external_api"
    GRAPH = "graph"


class EvidenceStance(str, Enum):
    """How a piece of evidence relates to the claim it was retrieved for."""

    SUPPORTING = "supporting"
    CONTRADICTING = "contradicting"
    NEUTRAL = "neutral"


class ClaimStatus(str, Enum):
    """How well the evidence backs one asserted statement.

    A claim is judged on its own evidence, not against rival explanations, so
    confidence is never divided between competing candidates.
    """

    #: corroborated by independent evidence, nothing credible against it
    SUPPORTED = "supported"
    #: some support, but thin or from a single source
    WEAK = "weak"
    #: credible evidence points the other way
    CONTRADICTED = "contradicted"
    #: the disproof search found decisive counter-evidence
    REFUTED = "refuted"
    #: not enough evidence either way
    INSUFFICIENT = "insufficient"


class ConfidenceLabel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INSUFFICIENT = "insufficient"

    @classmethod
    def from_score(cls, score: float) -> ConfidenceLabel:
        if score >= 0.80:
            return cls.HIGH
        if score >= 0.55:
            return cls.MEDIUM
        if score >= 0.30:
            return cls.LOW
        return cls.INSUFFICIENT


class AnswerStatus(str, Enum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    CONTESTED = "contested"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    DEGRADED = "degraded"
    FAILED = "failed"


class InvestigationStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    AWAITING_INPUT = "awaiting_input"
    COMPLETED = "completed"
    FAILED = "failed"


class SearchMode(str, Enum):
    FAST = "fast"
    DEEP = "deep"


class QueryIntent(str, Enum):
    LOOKUP_BY_ID = "lookup_by_id"
    STRUCTURED_QUERY = "structured_query"
    SEMANTIC_SEARCH = "semantic_search"
    MEDIA_LOCATION = "media_location"
    INVESTIGATION = "investigation"
    TEMPORAL = "temporal"
    CONTRADICTION = "contradiction"
    COMPARISON = "comparison"


class TraceStatus(str, Enum):
    STARTED = "started"
    OK = "ok"
    EMPTY = "empty"
    SKIPPED = "skipped"
    DEGRADED = "degraded"
    ERROR = "error"


class AgentName(str, Enum):
    BRAIN = "brain"
    DOCUMENT = "document_agent"
    IMAGE = "vision_agent"
    VIDEO = "video_agent"
    AUDIO = "audio_agent"
    DATABASE = "database_agent"
    GRAPH = "graph_agent"
    ENTITY_RESOLVER = "entity_resolver"
    CLAIM = "claim_builder"
    DISPROOF = "disproof_agent"
    VERIFIER = "verifier"
    TIMELINE = "timeline_builder"
    CONTRADICTION = "contradiction_radar"


class ModelRole(str, Enum):
    FAST_BRAIN = "fast_brain"
    DEEP_BRAIN = "deep_brain"
    VISION = "vision"
    EMBEDDING = "embedding"
    MM_EMBEDDING = "mm_embedding"
    RERANKER = "reranker"
    SPEECH = "speech"
    OCR = "ocr"


class ModelState(str, Enum):
    UNAVAILABLE = "unavailable"
    REGISTERED = "registered"
    LOADING = "loading"
    LOADED = "loaded"
    UNLOADING = "unloading"
    ERROR = "error"


class Role(str, Enum):
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"
