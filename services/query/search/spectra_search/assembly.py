"""Stage 5: turn scored candidates into :class:`SearchHit` records.

Provenance is *reconstructed*, never invented: the chunk's stored provenance
payload is rehydrated into a typed locator, and the asset record supplies the
object URI, versions and timestamps.  A hit an analyst cannot re-open is not
evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from spectra_config.logging import get_logger
from spectra_schemas import (
    Asset,
    AudioLocator,
    Chunk,
    DatabaseLocator,
    DocumentLocator,
    ExternalLocator,
    ImageLocator,
    Modality,
    Provenance,
    SearchHit,
    VideoLocator,
    parse_locator,
)

from .scoring import ScoredCandidate
from .snippets import build_snippet

log = get_logger(__name__)

#: Used when an asset record cannot be loaded; keeps the URI shape valid and
#: makes the gap obvious instead of silently emitting an empty string.
UNKNOWN_OBJECT_URI = "spectra://unknown"


def build_hit(
    scored: ScoredCandidate,
    asset: Asset | None,
    terms: tuple[str, ...],
    *,
    include_text: bool = False,
) -> SearchHit:
    chunk = scored.chunk
    return SearchHit(
        chunk_id=chunk.chunk_id,
        asset_id=chunk.asset_id,
        source_id=chunk.source_id,
        modality=chunk.modality,
        title=chunk.title or (asset.title if asset else None),
        snippet=build_snippet(chunk.text, terms),
        text=chunk.text if include_text else "",
        score=scored.breakdown.final,
        scores=scored.breakdown,
        provenance=build_provenance(chunk, asset),
        entities=list(chunk.entities),
        metadata=_hit_metadata(chunk, scored),
        occurred_at=chunk.occurred_at,
    )


def build_provenance(chunk: Chunk, asset: Asset | None) -> Provenance:
    """Rebuild the full chain of custody for one chunk."""
    payload = dict(chunk.provenance or {})
    if "locator" in payload:
        return _from_full_payload(payload, chunk, asset)
    locator = _locator_from(payload, chunk, asset)
    return Provenance(
        source_id=chunk.source_id,
        source_name=payload.get("source_name"),
        modality=chunk.modality,
        object_uri=str(payload.get("object_uri") or (asset.object_uri if asset else UNKNOWN_OBJECT_URI)),
        locator=locator,
        content_hash=payload.get("content_hash") or (asset.content_hash if asset else None),
        version=payload.get("version") or (asset.version if asset else None),
        version_status=str(payload.get("version_status") or (asset.version_status if asset else "unknown")),
        created_at=asset.created_at if asset else None,
        modified_at=asset.modified_at if asset else None,
        ingested_at=asset.ingested_at if asset else None,
        index_version=chunk.index_version,
    )


def _from_full_payload(payload: Mapping[str, Any], chunk: Chunk, asset: Asset | None) -> Provenance:
    merged = dict(payload)
    merged.setdefault("source_id", chunk.source_id)
    merged.setdefault("modality", chunk.modality)
    merged.setdefault("object_uri", asset.object_uri if asset else UNKNOWN_OBJECT_URI)
    merged.setdefault("index_version", chunk.index_version)
    try:
        return Provenance.model_validate(merged)
    except Exception as exc:  # noqa: BLE001 - a malformed record must not lose the hit
        log.warning("search.provenance_invalid", chunk_id=chunk.chunk_id, error=str(exc))
        return Provenance(
            source_id=chunk.source_id,
            modality=chunk.modality,
            object_uri=str(merged.get("object_uri") or UNKNOWN_OBJECT_URI),
            locator=_fallback_locator(chunk),
            index_version=chunk.index_version,
        )


def _locator_from(payload: Mapping[str, Any], chunk: Chunk, asset: Asset | None) -> Any:
    if payload.get("kind"):
        try:
            return parse_locator(dict(payload))
        except Exception as exc:  # noqa: BLE001 - fall back rather than drop evidence
            log.warning("search.locator_invalid", chunk_id=chunk.chunk_id, error=str(exc))
    return _fallback_locator(chunk, asset)


def _fallback_locator(chunk: Chunk, asset: Asset | None = None) -> Any:
    """Minimum viable locator built from the chunk's own identifiers."""
    metadata = chunk.metadata or {}
    if chunk.modality is Modality.IMAGE:
        return ImageLocator(image_id=chunk.asset_id)
    if chunk.modality is Modality.VIDEO:
        return VideoLocator(
            video_id=chunk.asset_id,
            scene_id=_opt_str(metadata.get("scene_id")),
            start_seconds=_opt_float(metadata.get("start_seconds")),
            end_seconds=_opt_float(metadata.get("end_seconds")),
        )
    if chunk.modality is Modality.AUDIO:
        return AudioLocator(
            audio_id=chunk.asset_id,
            segment_id=_opt_str(metadata.get("segment_id")),
            start_seconds=_opt_float(metadata.get("start_seconds")),
            end_seconds=_opt_float(metadata.get("end_seconds")),
        )
    if chunk.modality is Modality.DATABASE:
        return DatabaseLocator(
            source_id=chunk.source_id,
            table=str(metadata.get("table", "unknown")),
            primary_key=str(metadata.get("primary_key", "id")),
            record_id=str(metadata.get("record_id", chunk.chunk_id)),
        )
    if chunk.modality in (Modality.EXTERNAL, Modality.GRAPH):
        return ExternalLocator(
            source_id=chunk.source_id,
            resource=str(metadata.get("resource", chunk.asset_id)),
            record_id=_opt_str(metadata.get("record_id")),
        )
    return DocumentLocator(
        document_id=chunk.asset_id,
        page=_opt_int(metadata.get("page")),
        section=_opt_str(chunk.title or metadata.get("section")),
        paragraph=chunk.ordinal,
    )


def _hit_metadata(chunk: Chunk, scored: ScoredCandidate) -> dict[str, Any]:
    return {
        **dict(chunk.metadata or {}),
        "retrievers": list(scored.retrievers),
        "exact_id_match": scored.is_exact,
        "ordinal": chunk.ordinal,
    }


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _opt_int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _opt_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None
