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




class SearchMode(str, Enum):
    FAST = "fast"
    DEEP = "deep"




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
