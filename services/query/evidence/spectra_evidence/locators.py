"""Locator helpers: asset identity, dedupe signatures and sub-unit identifiers."""

from __future__ import annotations

from typing import Any

from spectra_schemas import Modality, Provenance

# The attribute carrying the owning asset id, per locator kind.
_ASSET_ATTRS: tuple[str, ...] = (
    "document_id",
    "image_id",
    "video_id",
    "audio_id",
    "record_id",
    "resource",
)


def asset_key(provenance: Provenance) -> str:
    """Identity of the object the evidence came from (document, video, row...)."""
    locator = provenance.locator
    for attr in _ASSET_ATTRS:
        value = getattr(locator, attr, None)
        if value:
            return str(value)
    return provenance.object_uri or provenance.source_id


def asset_node_key(provenance: Provenance) -> str:
    """Graph node id for the object the evidence came from.

    Database and external rows are namespaced by source and table so a row node
    can never collide with (and overwrite) the canonical entity node that shares
    the same record id.
    """
    locator = provenance.locator
    kind = getattr(locator, "kind", "unknown")
    if kind == "database":
        return f"{locator.source_id}:{locator.table}:{locator.record_id}"
    if kind == "external":
        parts = [locator.source_id, locator.resource, getattr(locator, "record_id", None) or ""]
        return ":".join(part for part in parts if part)
    return asset_key(provenance)


def locator_signature(provenance: Provenance) -> tuple[Any, ...]:
    """Asset + position signature used to collapse duplicate evidence."""
    locator = provenance.locator
    kind = getattr(locator, "kind", "unknown")
    fields: tuple[str, ...]
    if kind == "document":
        fields = ("page", "section", "paragraph", "char_start")
    elif kind == "image":
        fields = ("region",)
    elif kind == "video":
        fields = ("scene_id", "frame_id", "start_seconds")
    elif kind == "audio":
        fields = ("segment_id", "start_seconds")
    elif kind == "database":
        fields = ("table", "column")
    else:
        fields = ("resource",)
    return (kind, asset_key(provenance), *(getattr(locator, field, None) for field in fields))


def media_offset_seconds(provenance: Provenance) -> float | None:
    """Start offset for video/audio locators, ``None`` for everything else."""
    return getattr(provenance.locator, "start_seconds", None)


def unit_identifier(provenance: Provenance, fallback: str = "") -> str:
    """Stable id for the sub-asset unit (page, scene, frame, segment, row)."""
    locator = provenance.locator
    kind = getattr(locator, "kind", "unknown")
    asset = asset_key(provenance)
    if kind == "document" and getattr(locator, "page", None) is not None:
        return f"{asset}#p{locator.page}"
    if kind in {"video", "audio"}:
        marker = (
            getattr(locator, "frame_id", None)
            or getattr(locator, "scene_id", None)
            or getattr(locator, "segment_id", None)
        )
        if marker:
            return f"{asset}#{marker}"
        start = getattr(locator, "start_seconds", None)
        if start is not None:
            return f"{asset}#t{int(start)}"
    if kind in {"database", "external"}:
        return asset_node_key(provenance)
    return fallback or asset


def modality_of(provenance: Provenance) -> Modality:
    return provenance.modality
