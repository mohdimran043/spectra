"""Provenance locators.

Every retrievable unit in SPECTRA carries a locator that is precise enough to
re-open the exact spot a claim came from: a PDF page, a video second, an audio
segment, a database row.  Locators are pure identifiers plus an ``object_uri`` -
never a local filesystem path - so the same record resolves identically on a
laptop and on a distributed cluster.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .enums import Modality


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DocumentLocator(_Frozen):
    kind: Literal["document"] = "document"
    document_id: str
    page: int | None = None
    section: str | None = None
    paragraph: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    bbox: tuple[float, float, float, float] | None = None

    def human(self) -> str:
        bits = [f"Document: {self.document_id}"]
        if self.page is not None:
            bits.append(f"Page: {self.page}")
        if self.section:
            bits.append(f"Section: {self.section}")
        return " | ".join(bits)


class ImageLocator(_Frozen):
    kind: Literal["image"] = "image"
    image_id: str
    region: tuple[float, float, float, float] | None = None

    def human(self) -> str:
        return f"Image: {self.image_id}"


class VideoLocator(_Frozen):
    kind: Literal["video"] = "video"
    video_id: str
    scene_id: str | None = None
    frame_id: str | None = None
    start_seconds: float | None = None
    end_seconds: float | None = None

    def human(self) -> str:
        if self.start_seconds is None:
            return f"Video: {self.video_id}"
        return f"Video: {self.video_id} @ {_hms(self.start_seconds)}"


class AudioLocator(_Frozen):
    kind: Literal["audio"] = "audio"
    audio_id: str
    segment_id: str | None = None
    start_seconds: float | None = None
    end_seconds: float | None = None
    speaker: str | None = None

    def human(self) -> str:
        if self.start_seconds is None:
            return f"Audio: {self.audio_id}"
        end = _hms(self.end_seconds) if self.end_seconds is not None else ""
        return f"Audio: {self.audio_id} {_hms(self.start_seconds)} - {end}".strip()


class DatabaseLocator(_Frozen):
    kind: Literal["database"] = "database"
    source_id: str
    table: str
    primary_key: str
    record_id: str
    column: str | None = None

    def human(self) -> str:
        return f"{self.table}.{self.primary_key}={self.record_id}"


class ExternalLocator(_Frozen):
    kind: Literal["external"] = "external"
    source_id: str
    resource: str
    record_id: str | None = None

    def human(self) -> str:
        return f"{self.source_id}:{self.resource}"


Locator = (
    DocumentLocator | ImageLocator | VideoLocator | AudioLocator | DatabaseLocator | ExternalLocator
)

LOCATOR_TYPES: dict[str, type[BaseModel]] = {
    "document": DocumentLocator,
    "image": ImageLocator,
    "video": VideoLocator,
    "audio": AudioLocator,
    "database": DatabaseLocator,
    "external": ExternalLocator,
}


def parse_locator(payload: dict) -> Locator:
    """Rebuild a locator from its serialised form."""
    kind = payload.get("kind")
    cls = LOCATOR_TYPES.get(str(kind))
    if cls is None:
        raise ValueError(f"unknown locator kind: {kind!r}")
    return cls.model_validate(payload)  # type: ignore[return-value]


class Provenance(BaseModel):
    """Full chain-of-custody for one retrievable unit."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    source_name: str | None = None
    modality: Modality
    object_uri: str = Field(description="Canonical storage URI, e.g. spectra://objects/<sha256>")
    locator: Locator = Field(discriminator="kind")
    content_hash: str | None = None
    version: str | None = None
    version_status: str = "unknown"
    created_at: datetime | None = None
    modified_at: datetime | None = None
    ingested_at: datetime | None = None
    index_version: str | None = None

    def human(self) -> str:
        return self.locator.human()  # type: ignore[union-attr]


def _hms(seconds: float | None) -> str:
    if seconds is None:
        return "--:--:--"
    total = int(seconds)
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def format_timestamp(seconds: float | None) -> str:
    """Public helper - ``3742.0 -> '01:02:22'``."""
    return _hms(seconds)
