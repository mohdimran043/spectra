"""Search endpoints: unified, per-modality and image-driven."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel
from spectra_schemas import Modality, SearchRequest, SearchResponse

from ..dependencies import Container, Ctx, service_or_503
from ..errors import UploadRejected

router = APIRouter(tags=["search"])


class ImageSearchResponse(BaseModel):
    """Image->everything: the search results plus what we understood from the image."""

    search: SearchResponse
    understanding: dict


@router.post("/search", response_model=SearchResponse)
async def unified_search(body: SearchRequest, container: Container, ctx: Ctx) -> SearchResponse:
    service = service_or_503(container, "search")
    return await service.search(body, ctx)


async def _modality_search(
    body: SearchRequest, container: Container, ctx: Ctx, modality: Modality
) -> SearchResponse:
    service = service_or_503(container, "search")
    scoped = body.model_copy(
        update={"filters": body.filters.model_copy(update={"modalities": [modality]})}
    )
    return await service.search(scoped, ctx)


@router.post("/search/document", response_model=SearchResponse)
async def search_documents(body: SearchRequest, container: Container, ctx: Ctx) -> SearchResponse:
    return await _modality_search(body, container, ctx, Modality.DOCUMENT)


@router.post("/search/video", response_model=SearchResponse)
async def search_videos(body: SearchRequest, container: Container, ctx: Ctx) -> SearchResponse:
    return await _modality_search(body, container, ctx, Modality.VIDEO)


@router.post("/search/audio", response_model=SearchResponse)
async def search_audio(body: SearchRequest, container: Container, ctx: Ctx) -> SearchResponse:
    return await _modality_search(body, container, ctx, Modality.AUDIO)


@router.post("/search/image", response_model=ImageSearchResponse)
async def search_image(
    container: Container,
    ctx: Ctx,
    file: UploadFile | None = File(default=None),
    image_asset_id: str | None = Form(default=None),
    query: str = Form(default=""),
) -> ImageSearchResponse:
    """Upload an image (or reference one already ingested) and search everything it implies.

    The uploaded image is ingested first, so OCR / captioning / embedding happen on the
    ingestion path - never at query time.
    """
    search = service_or_503(container, "search")

    asset_id = image_asset_id
    if asset_id is None:
        if file is None:
            raise UploadRejected("provide either a file or image_asset_id")
        ingestion = service_or_503(container, "ingestion")
        data = await file.read()
        job = await ingestion.ingest_upload(
            filename=file.filename or "upload.png",
            data=data,
            source_id="src_uploads",
            permissions=[ctx.role.value],
        )
        await ingestion.process_job(job.job_id)
        refreshed = await container.storage.repository.get_job(job.job_id)
        asset_id = (refreshed or job).asset_id
        if asset_id is None:
            raise UploadRejected("the uploaded image could not be indexed")

    result = await search.search_by_image(asset_id, ctx, query=query)
    if isinstance(result, tuple):
        response, understanding = result
    else:
        response, understanding = result, {}
    return ImageSearchResponse(search=response, understanding=understanding)
