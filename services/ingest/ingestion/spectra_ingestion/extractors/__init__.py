"""Content extractors plus the media-type -> extractor routing table."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .base import (
    BBox,
    BlockKind,
    EmbeddedImage,
    ExtractedBlock,
    ExtractionError,
    markdown_table,
    normalise_text,
    sequence_blocks,
)
from .detect import (
    ALLOWED_MEDIA_TYPES,
    EXTENSION_MEDIA_TYPES,
    MEDIA_TYPE_KINDS,
    TEXT_MEDIA_TYPES,
    canonical_media_type,
    detect_bytes,
    detect_media_type,
    extension_media_type,
    kind_for_media_type,
    sniff_bytes,
)
from .office import extract_docx, extract_pptx, extract_xlsx
from .pdf import extract as extract_pdf
from .pdf import extract_images as extract_pdf_images
from .plain import extract_csv, extract_html, extract_json, extract_markdown, extract_text

Extractor = Callable[[str | Path], list[ExtractedBlock]]

#: The only place that says which parser owns which media type.
EXTRACTORS: dict[str, Extractor] = {
    "application/pdf": extract_pdf,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": extract_docx,
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": extract_pptx,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": extract_xlsx,
    "text/csv": extract_csv,
    "text/plain": extract_text,
    "text/markdown": extract_markdown,
    "application/json": extract_json,
    "text/html": extract_html,
}


def get_extractor(media_type: str) -> Extractor | None:
    """Return the parser for a canonical media type, or ``None`` when unsupported."""
    return EXTRACTORS.get(canonical_media_type(media_type) or "")


__all__ = [
    "ALLOWED_MEDIA_TYPES",
    "EXTENSION_MEDIA_TYPES",
    "EXTRACTORS",
    "MEDIA_TYPE_KINDS",
    "TEXT_MEDIA_TYPES",
    "BBox",
    "BlockKind",
    "EmbeddedImage",
    "ExtractedBlock",
    "ExtractionError",
    "Extractor",
    "canonical_media_type",
    "detect_bytes",
    "detect_media_type",
    "extension_media_type",
    "extract_csv",
    "extract_docx",
    "extract_html",
    "extract_json",
    "extract_markdown",
    "extract_pdf",
    "extract_pdf_images",
    "extract_pptx",
    "extract_text",
    "extract_xlsx",
    "get_extractor",
    "kind_for_media_type",
    "markdown_table",
    "normalise_text",
    "sequence_blocks",
    "sniff_bytes",
]
