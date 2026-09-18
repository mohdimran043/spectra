"""Parsing and validation of ``spectra://objects/...`` URIs.

Object URIs arrive from ingestion metadata, from the API and from model output,
so they are treated as hostile input.  A URI is only ever accepted when it
matches the content-addressed shape exactly; the parsed parts - never the raw
string - are what a backend turns into a filesystem path or an S3 key.  This is
the path-traversal boundary for the object layer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

URI_SCHEME = "spectra"
URI_ROOT = "objects"
SHA_PATTERN = r"[0-9a-f]{6,64}"
EXTENSION_PATTERN = r"[A-Za-z0-9]{1,8}"
PREFIX_LENGTH = 2

OBJECT_URI_RE = re.compile(
    rf"^{URI_SCHEME}://{URI_ROOT}/(?P<prefix>[0-9a-f]{{{PREFIX_LENGTH}}})/"
    rf"(?P<sha>{SHA_PATTERN})(?:\.(?P<extension>{EXTENSION_PATTERN}))?$"
)


class ObjectUriError(ValueError):
    """Raised when a URI is not a well-formed SPECTRA object reference."""


@dataclass(frozen=True)
class ObjectRef:
    """The validated components of one object URI."""

    prefix: str
    sha: str
    extension: str

    @property
    def filename(self) -> str:
        return f"{self.sha}.{self.extension}" if self.extension else self.sha

    @property
    def relative_path(self) -> str:
        return f"{self.prefix}/{self.filename}"

    @property
    def key(self) -> str:
        return f"{URI_ROOT}/{self.relative_path}"

    @property
    def uri(self) -> str:
        return f"{URI_SCHEME}://{URI_ROOT}/{self.relative_path}"


def parse_object_uri(uri: str) -> ObjectRef:
    """Validate ``uri`` and return its parts, or raise ``ObjectUriError``."""
    match = OBJECT_URI_RE.match(uri or "")
    if match is None:
        raise ObjectUriError(
            f"invalid object uri {uri!r}: expected spectra://objects/<2 hex>/<sha>[.<ext>]"
        )
    prefix = match.group("prefix")
    sha = match.group("sha")
    if prefix != sha[:PREFIX_LENGTH]:
        raise ObjectUriError(
            f"invalid object uri {uri!r}: shard {prefix!r} does not match digest prefix {sha[:PREFIX_LENGTH]!r}"
        )
    return ObjectRef(prefix=prefix, sha=sha, extension=match.group("extension") or "")


def resolve_within(root: Path, ref: ObjectRef) -> Path:
    """Map a validated reference to a path and prove it stays inside ``root``."""
    base = root.resolve()
    candidate = (base / ref.prefix / ref.filename).resolve()
    if not candidate.is_relative_to(base):
        raise ObjectUriError(f"resolved path {candidate} escapes object root {base}")
    return candidate
