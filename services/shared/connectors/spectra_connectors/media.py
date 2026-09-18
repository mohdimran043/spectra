"""Filename -> media type -> :class:`AssetKind` mapping.

Shared by every connector that discovers *files* (local folder, S3, uploads) so
a ``.mp4`` is classified identically no matter where it was found.
"""

from __future__ import annotations

import mimetypes
from collections.abc import Mapping

from spectra_schemas.enums import AssetKind

DEFAULT_MEDIA_TYPE = "application/octet-stream"

#: Extensions the stdlib ``mimetypes`` table does not know or gets wrong.
_EXTRA_TYPES: Mapping[str, str] = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".mkv": "video/x-matroska",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".opus": "audio/opus",
    ".parquet": "application/vnd.apache.parquet",
    ".jsonl": "application/x-ndjson",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

_TABLE_TYPES = frozenset(
    {
        "text/csv",
        "text/tab-separated-values",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.apache.parquet",
        "application/x-ndjson",
    }
)


def guess_media_type(name: str) -> str:
    """Best-effort media type for ``name`` - never raises."""
    lowered = name.lower()
    for extension, media_type in _EXTRA_TYPES.items():
        if lowered.endswith(extension):
            return media_type
    guessed, _ = mimetypes.guess_type(lowered)
    return guessed or DEFAULT_MEDIA_TYPE


def kind_for_media_type(media_type: str) -> AssetKind:
    """Map a media type onto the closed :class:`AssetKind` vocabulary."""
    normalised = (media_type or "").split(";", 1)[0].strip().lower()
    if normalised in _TABLE_TYPES:
        return AssetKind.TABLE
    family = normalised.split("/", 1)[0]
    if family == "image":
        return AssetKind.IMAGE
    if family == "video":
        return AssetKind.VIDEO
    if family == "audio":
        return AssetKind.AUDIO
    return AssetKind.DOCUMENT


def classify(name: str) -> tuple[str, AssetKind]:
    """Return ``(media_type, kind)`` for a filename in one call."""
    media_type = guess_media_type(name)
    return media_type, kind_for_media_type(media_type)
