"""One ingestion pipeline per modality, all sharing :mod:`.base`."""

from __future__ import annotations

from .audio import AudioPipeline
from .base import (
    STAGE_EMBED,
    STAGE_EXTRACT,
    STAGE_INDEX,
    BasePipeline,
    IngestResult,
    JobContext,
    build_chunk,
)
from .database import DatabasePipeline, TableSchema
from .document import DocumentPipeline, UnsupportedDocument
from .image import ImagePipeline
from .video import VideoPipeline

__all__ = [
    "STAGE_EMBED",
    "STAGE_EXTRACT",
    "STAGE_INDEX",
    "AudioPipeline",
    "BasePipeline",
    "DatabasePipeline",
    "DocumentPipeline",
    "ImagePipeline",
    "IngestResult",
    "JobContext",
    "TableSchema",
    "UnsupportedDocument",
    "VideoPipeline",
    "build_chunk",
]
