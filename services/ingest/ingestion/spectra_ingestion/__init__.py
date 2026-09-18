"""SPECTRA ingestion service.

All expensive processing - parsing, OCR, captioning, transcription, scene
detection, embedding - happens here, at ingestion time.  The search path only
ever reads what this package wrote.
"""

from __future__ import annotations

from .chunking import (
    DEFAULT_OVERLAP_RATIO,
    DEFAULT_TARGET_TOKENS,
    ChunkDraft,
    TranscriptWindow,
    chunk_blocks,
    merge_transcript_segments,
)
from .entity_hook import EntityExtractor, RegexEntityExtractor, annotate_chunks
from .extractors import EXTRACTORS, ExtractedBlock, detect_media_type, get_extractor
from .indexer import Indexer, IndexReport
from .pipelines import (
    AudioPipeline,
    BasePipeline,
    DatabasePipeline,
    DocumentPipeline,
    ImagePipeline,
    IngestResult,
    JobContext,
    TableSchema,
    VideoPipeline,
)
from .security import UploadRejected, ValidatedUpload, sanitise_filename, validate_upload
from .service import IngestionService

__all__ = [
    "DEFAULT_OVERLAP_RATIO",
    "DEFAULT_TARGET_TOKENS",
    "EXTRACTORS",
    "AudioPipeline",
    "BasePipeline",
    "ChunkDraft",
    "DatabasePipeline",
    "DocumentPipeline",
    "EntityExtractor",
    "ExtractedBlock",
    "ImagePipeline",
    "IndexReport",
    "Indexer",
    "IngestResult",
    "IngestionService",
    "JobContext",
    "RegexEntityExtractor",
    "TableSchema",
    "TranscriptWindow",
    "UploadRejected",
    "ValidatedUpload",
    "VideoPipeline",
    "annotate_chunks",
    "chunk_blocks",
    "detect_media_type",
    "get_extractor",
    "merge_transcript_segments",
    "sanitise_filename",
    "validate_upload",
]
