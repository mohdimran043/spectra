"""Asset metadata and byte serving (range-aware, so video seeking works)."""

from __future__ import annotations

import mimetypes
import re

from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse
from spectra_schemas import Asset

from ..dependencies import Container, Ctx
from ..errors import NotFound, PermissionDenied, ValidationRejected

router = APIRouter(tags=["assets"])

RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
STREAM_CHUNK = 256 * 1024


async def _load(container: Container, asset_id: str, ctx: Ctx) -> Asset:
    asset = await container.storage.repository.get_asset(asset_id)
    if asset is None:
        raise NotFound(f"unknown asset: {asset_id!r}")
    if not ctx.may_read_source(asset.source_id, asset.permissions):
        raise PermissionDenied(f"role '{ctx.role.value}' may not read this asset")
    return asset


@router.get("/assets/{asset_id}", response_model=Asset)
async def get_asset(asset_id: str, container: Container, ctx: Ctx) -> Asset:
    return await _load(container, asset_id, ctx)


@router.get("/assets/{asset_id}/content")
async def get_asset_content(asset_id: str, request: Request, container: Container, ctx: Ctx):
    asset = await _load(container, asset_id, ctx)
    data = await container.storage.objects.get(asset.object_uri)
    total = len(data)
    media_type = asset.media_type or mimetypes.guess_type(asset.title)[0] or "application/octet-stream"

    range_header = request.headers.get("range")
    if not range_header:
        return Response(
            content=data,
            media_type=media_type,
            headers={"Accept-Ranges": "bytes", "Content-Length": str(total)},
        )

    match = RANGE_RE.match(range_header.strip())
    if match is None:
        raise ValidationRejected(f"malformed Range header: {range_header!r}")
    start_raw, end_raw = match.groups()
    start = int(start_raw) if start_raw else 0
    end = int(end_raw) if end_raw else total - 1
    if start >= total or start > end:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{total}"})
    end = min(end, total - 1)
    body = data[start : end + 1]

    def _iter():
        for offset in range(0, len(body), STREAM_CHUNK):
            yield body[offset : offset + STREAM_CHUNK]

    return StreamingResponse(
        _iter(),
        status_code=206,
        media_type=media_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{total}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(len(body)),
        },
    )


@router.get("/assets/{asset_id}/thumbnail")
async def get_thumbnail(asset_id: str, container: Container, ctx: Ctx) -> Response:
    asset = await _load(container, asset_id, ctx)
    uri = asset.metadata.get("thumbnail_uri")
    if not uri:
        raise NotFound("this asset has no generated thumbnail")
    return Response(await container.storage.objects.get(str(uri)), media_type="image/jpeg")


@router.get("/assets/{asset_id}/page/{page}")
async def get_page_render(asset_id: str, page: int, container: Container, ctx: Ctx) -> Response:
    asset = await _load(container, asset_id, ctx)
    renders = asset.metadata.get("page_renders") or {}
    uri = renders.get(str(page))
    if not uri:
        raise NotFound(f"no rendered image for page {page}")
    return Response(await container.storage.objects.get(str(uri)), media_type="image/png")


@router.get("/assets", response_model=list[Asset])
async def list_assets(
    container: Container,
    ctx: Ctx,
    source_id: str | None = None,
    kind: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Asset]:
    assets = await container.storage.repository.list_assets(
        source_id=source_id, kind=kind, limit=limit, offset=offset
    )
    return [a for a in assets if ctx.may_read_source(a.source_id, a.permissions)]
