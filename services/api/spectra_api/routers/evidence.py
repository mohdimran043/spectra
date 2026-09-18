"""Evidence item retrieval with resolvable provenance."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..dependencies import Container, Ctx, service_or_503
from ..errors import NotFound

router = APIRouter(tags=["evidence"])


@router.get("/evidence/{evidence_id}")
async def get_evidence(evidence_id: str, container: Container, ctx: Ctx) -> dict[str, Any]:
    service = service_or_503(container, "evidence")
    item = await service.ledger.fetch(evidence_id)
    if item is None:
        raise NotFound(f"unknown evidence: {evidence_id!r}")
    if not ctx.may_read_source(item.provenance.source_id):
        raise NotFound(f"unknown evidence: {evidence_id!r}")

    payload = item.model_dump(mode="json")
    payload["citation"] = item.citation()
    payload["weight"] = item.weight
    payload["open_target"] = _open_target(item)
    return payload


def _open_target(item) -> dict[str, Any]:
    """Tell the UI exactly how to open this piece of evidence."""
    locator = item.provenance.locator
    kind = getattr(locator, "kind", "")
    if kind == "document":
        return {
            "type": "document_page",
            "asset_ref": locator.document_id,
            "page": locator.page,
            "section": locator.section,
        }
    if kind == "image":
        return {"type": "image", "asset_ref": locator.image_id, "region": locator.region}
    if kind == "video":
        return {
            "type": "video_timestamp",
            "asset_ref": locator.video_id,
            "start_seconds": locator.start_seconds,
            "end_seconds": locator.end_seconds,
        }
    if kind == "audio":
        return {
            "type": "audio_timestamp",
            "asset_ref": locator.audio_id,
            "start_seconds": locator.start_seconds,
            "end_seconds": locator.end_seconds,
        }
    if kind == "database":
        return {
            "type": "database_record",
            "source_id": locator.source_id,
            "table": locator.table,
            "record_id": locator.record_id,
        }
    return {"type": "external", "source_id": item.provenance.source_id}
