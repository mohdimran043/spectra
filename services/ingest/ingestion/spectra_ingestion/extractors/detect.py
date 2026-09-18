"""Media-type detection - the single source of truth for pipeline routing.

Everything that decides "is this a document, an image, an audio file or a
video" goes through :func:`detect_media_type` (path) or :func:`detect_bytes`
(in-memory upload).  Content sniffing wins over the declared type so a renamed
executable cannot masquerade as a PDF.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Final

import filetype
from spectra_config.logging import get_logger
from spectra_schemas import AssetKind

log = get_logger(__name__)

#: How many bytes are enough for every magic-number matcher we rely on.
SNIFF_BYTES: Final[int] = 4096

DOCUMENT_EXTENSIONS: Final[dict[str, str]] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".json": "application/json",
    ".html": "text/html",
    ".htm": "text/html",
}

IMAGE_EXTENSIONS: Final[dict[str, str]] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}

AUDIO_EXTENSIONS: Final[dict[str, str]] = {
    ".wav": "audio/x-wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/m4a",
    ".flac": "audio/x-flac",
    ".aac": "audio/aac",
}

VIDEO_EXTENSIONS: Final[dict[str, str]] = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".avi": "video/x-msvideo",
}

EXTENSION_MEDIA_TYPES: Final[dict[str, str]] = {
    **DOCUMENT_EXTENSIONS,
    **IMAGE_EXTENSIONS,
    **AUDIO_EXTENSIONS,
    **VIDEO_EXTENSIONS,
}

#: Alternative magic-number results that mean the same thing as the canonical type.
MEDIA_TYPE_ALIASES: Final[dict[str, str]] = {
    "audio/wav": "audio/x-wav",
    "audio/wave": "audio/x-wav",
    "audio/vnd.wave": "audio/x-wav",
    "audio/x-m4a": "audio/m4a",
    "audio/mp4": "audio/m4a",
    "audio/mp3": "audio/mpeg",
    "audio/flac": "audio/x-flac",
    "video/x-msvideo": "video/x-msvideo",
    "video/avi": "video/x-msvideo",
    "video/quicktime": "video/quicktime",
    "image/tif": "image/tiff",
    "image/jpg": "image/jpeg",
    "application/xhtml+xml": "text/html",
    "text/x-markdown": "text/markdown",
}

MEDIA_TYPE_KINDS: Final[dict[str, AssetKind]] = {
    **{media: AssetKind.DOCUMENT for media in DOCUMENT_EXTENSIONS.values()},
    **{media: AssetKind.IMAGE for media in IMAGE_EXTENSIONS.values()},
    **{media: AssetKind.AUDIO for media in AUDIO_EXTENSIONS.values()},
    **{media: AssetKind.VIDEO for media in VIDEO_EXTENSIONS.values()},
}

#: Media types an upload is allowed to carry - derived from the accepted formats.
ALLOWED_MEDIA_TYPES: Final[frozenset[str]] = frozenset(MEDIA_TYPE_KINDS)

#: Types magic-number sniffing cannot see, so the extension is authoritative.
TEXT_MEDIA_TYPES: Final[frozenset[str]] = frozenset(
    {"text/csv", "text/plain", "text/markdown", "application/json", "text/html"}
)

OOXML_MEDIA_TYPES: Final[frozenset[str]] = frozenset(
    {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
)

DEFAULT_MEDIA_TYPE: Final[str] = "application/octet-stream"


def canonical_media_type(media_type: str | None) -> str | None:
    """Fold equivalent spellings onto one canonical media type."""
    if not media_type:
        return None
    value = media_type.split(";")[0].strip().lower()
    return MEDIA_TYPE_ALIASES.get(value, value) or None


def extension_media_type(filename: str | Path | None) -> str | None:
    """Canonical media type implied by a filename extension, if we accept it."""
    if filename is None:
        return None
    suffix = Path(str(filename)).suffix.lower()
    return EXTENSION_MEDIA_TYPES.get(suffix)


def sniff_bytes(data: bytes) -> str | None:
    """Magic-number media type, or ``None`` when the content is not binary-typed."""
    if not data:
        return None
    try:
        guess = filetype.guess(data[:SNIFF_BYTES])
    except Exception as exc:  # pragma: no cover - filetype is defensive already
        log.warning("detect.sniff_failed", error=str(exc))
        return None
    return canonical_media_type(guess.mime) if guess is not None else None


def kind_for_media_type(media_type: str | None) -> AssetKind | None:
    """AssetKind for a canonical media type, or ``None`` when unsupported."""
    if not media_type:
        return None
    return MEDIA_TYPE_KINDS.get(canonical_media_type(media_type) or "")


def detect_bytes(
    data: bytes, filename: str | Path | None = None, declared: str | None = None
) -> tuple[str, AssetKind]:
    """Resolve ``(media_type, AssetKind)`` for an in-memory payload."""
    sniffed = sniff_bytes(data)
    by_extension = extension_media_type(filename)
    return _classify(sniffed, by_extension, canonical_media_type(declared), filename)


def detect_media_type(path: str | Path, declared: str | None = None) -> tuple[str, AssetKind]:
    """Resolve ``(media_type, AssetKind)`` for a file on disk.

    Raises ``FileNotFoundError`` when the path does not exist - callers must not
    silently index a file they never read.
    """
    target = Path(path)
    with target.open("rb") as handle:
        header = handle.read(SNIFF_BYTES)
    return detect_bytes(header, target.name, declared)


def _classify(
    sniffed: str | None,
    by_extension: str | None,
    declared: str | None,
    filename: str | Path | None,
) -> tuple[str, AssetKind]:
    """Pick the winning media type: content first, then extension, then declared."""
    if sniffed in OOXML_MEDIA_TYPES or (sniffed == "application/zip" and by_extension in OOXML_MEDIA_TYPES):
        media_type = by_extension or sniffed or DEFAULT_MEDIA_TYPE
        return media_type, MEDIA_TYPE_KINDS.get(media_type, AssetKind.DOCUMENT)

    for candidate in (sniffed, by_extension, declared, _guess_by_mimetypes(filename)):
        kind = kind_for_media_type(candidate)
        if kind is not None and candidate is not None:
            return candidate, kind

    fallback = sniffed or by_extension or declared or DEFAULT_MEDIA_TYPE
    log.info("detect.unsupported_media_type", media_type=fallback, filename=str(filename or ""))
    return fallback, AssetKind.DOCUMENT


def _guess_by_mimetypes(filename: str | Path | None) -> str | None:
    if filename is None:
        return None
    guessed, _ = mimetypes.guess_type(str(filename))
    return canonical_media_type(guessed)
