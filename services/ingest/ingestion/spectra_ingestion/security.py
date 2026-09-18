"""Upload security: size limits, sniffed-type allowlist, filename sanitisation, AV.

Every byte that enters SPECTRA from outside passes through :func:`validate_upload`
before anything touches a parser, and lands in a per-job directory it cannot
escape.
"""

from __future__ import annotations

import asyncio
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from spectra_config import Settings
from spectra_config.logging import get_logger
from spectra_schemas import AssetKind, content_hash

from .extractors.detect import (
    ALLOWED_MEDIA_TYPES,
    OOXML_MEDIA_TYPES,
    TEXT_MEDIA_TYPES,
    extension_media_type,
    kind_for_media_type,
    sniff_bytes,
)

log = get_logger(__name__)

ANTIVIRUS_TIMEOUT_SECONDS: Final[int] = 300
MAX_FILENAME_CHARS: Final[int] = 180
FALLBACK_FILENAME: Final[str] = "upload"
TEXT_PROBE_BYTES: Final[int] = 8192
COMMENT_PREFIX: Final[str] = "#"
UNSAFE_CHARS: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9._-]+")


class UploadRejected(ValueError):
    """An upload failed a security check and was never written to disk."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class ValidatedUpload:
    """The trusted view of an upload, produced only after every check passed."""

    filename: str
    media_type: str
    kind: AssetKind
    size_bytes: int
    content_hash: str
    extension: str


def sanitise_filename(filename: str) -> str:
    """Strip directories, traversal and shell-hostile characters from a name."""
    candidate = str(filename or "").replace("\\", "/").split("/")[-1].strip()
    candidate = candidate.replace("..", "_")
    candidate = UNSAFE_CHARS.sub("_", candidate).strip("._-")
    if not candidate:
        return FALLBACK_FILENAME
    suffix = Path(candidate).suffix
    stem = Path(candidate).stem[: MAX_FILENAME_CHARS - len(suffix)] or FALLBACK_FILENAME
    return f"{stem}{suffix}"


def validate_upload(filename: str, data: bytes, settings: Settings) -> ValidatedUpload:
    """Run every upload check, raising :class:`UploadRejected` on the first failure."""
    if not data:
        raise UploadRejected("empty_upload", "the uploaded file contains no data")
    if len(data) > settings.max_upload_bytes:
        raise UploadRejected(
            "too_large", f"{len(data)} bytes exceeds the {settings.max_upload_bytes} byte limit"
        )

    safe_name = sanitise_filename(filename)
    extension = Path(safe_name).suffix.lower()
    declared = extension_media_type(safe_name)
    if declared is None:
        raise UploadRejected("unsupported_extension", f"{extension or 'no extension'} is not accepted")

    media_type = _resolve_media_type(data, declared, safe_name)
    kind = kind_for_media_type(media_type)
    if kind is None:  # pragma: no cover - guarded by the allowlist above
        raise UploadRejected("unsupported_media_type", f"{media_type} is not accepted")
    return ValidatedUpload(
        filename=safe_name,
        media_type=media_type,
        kind=kind,
        size_bytes=len(data),
        content_hash=content_hash(data),
        extension=extension,
    )


def job_directory(settings: Settings, job_id: str) -> Path:
    """Per-job upload directory, created private to the service account."""
    safe_job = UNSAFE_CHARS.sub("_", job_id) or FALLBACK_FILENAME
    directory = settings.upload_dir / safe_job
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    return directory


def staged_path(settings: Settings, job_id: str, filename: str) -> Path:
    """Absolute path an upload may be written to - always inside its job directory."""
    directory = job_directory(settings, job_id)
    target = (directory / sanitise_filename(filename)).resolve()
    if not str(target).startswith(str(directory.resolve()) + "/"):
        raise UploadRejected("path_traversal", f"{filename} escapes its job directory")
    return target


async def scan_for_malware(hook: str, path: Path) -> None:
    """Run the configured antivirus hook; a non-zero exit rejects the upload."""
    raw = (hook or "").strip()
    if raw.startswith(COMMENT_PREFIX):  # a commented-out .env value is not a command
        log.warning("upload.antivirus_hook_ignored", hook=raw[:60])
        return
    command = shlex.split(raw) if raw else []
    if not command:
        return
    args = [*command, str(path)]
    try:
        process = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    except OSError as exc:
        raise UploadRejected("antivirus_unavailable", f"cannot run {command[0]}: {exc}") from exc

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=ANTIVIRUS_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise UploadRejected("antivirus_timeout", f"{command[0]} did not finish in time") from exc

    if process.returncode != 0:
        detail = (stderr or stdout).decode("utf-8", "replace").strip()[:400]
        log.warning("upload.antivirus_rejected", path=str(path), detail=detail)
        raise UploadRejected("antivirus_rejected", detail or f"{command[0]} exited {process.returncode}")


def _resolve_media_type(data: bytes, declared: str, filename: str) -> str:
    sniffed = sniff_bytes(data)
    if sniffed is None:
        return _validate_text_upload(data, declared, filename)
    if sniffed == "application/zip" and declared in OOXML_MEDIA_TYPES:
        return declared
    if sniffed not in ALLOWED_MEDIA_TYPES:
        raise UploadRejected("blocked_media_type", f"{filename} contains {sniffed}, which is not accepted")

    declared_kind, sniffed_kind = kind_for_media_type(declared), kind_for_media_type(sniffed)
    if declared_kind is not sniffed_kind:
        raise UploadRejected(
            "extension_mismatch", f"{filename} claims {declared} but contains {sniffed}"
        )
    if declared_kind is AssetKind.DOCUMENT and declared != sniffed:
        raise UploadRejected(
            "extension_mismatch", f"{filename} claims {declared} but contains {sniffed}"
        )
    return sniffed


def _validate_text_upload(data: bytes, declared: str, filename: str) -> str:
    """Nothing sniffed - only the text formats may take this path."""
    if declared not in TEXT_MEDIA_TYPES:
        raise UploadRejected("unrecognised_content", f"{filename} does not contain valid {declared} data")
    if b"\x00" in data[:TEXT_PROBE_BYTES]:
        raise UploadRejected("binary_content", f"{filename} claims {declared} but contains binary data")
    return declared
