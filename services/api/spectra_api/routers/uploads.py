"""Asynchronous upload ingestion with a visible status machine."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile, status
from spectra_schemas import IngestJob

from ..background import spawn
from ..dependencies import Container, Ctx, CtxUpload, service_or_503
from ..errors import NotFound, PayloadTooLarge, UploadRejected

router = APIRouter(tags=["uploads"])

UPLOAD_SOURCE_ID = "src_uploads"
READ_CHUNK_BYTES = 1024 * 1024


@router.post("/uploads", status_code=status.HTTP_202_ACCEPTED, response_model=IngestJob)
async def create_upload(
    container: Container,
    ctx: CtxUpload,
    file: UploadFile = File(...),
    source_id: str = Form(default=UPLOAD_SOURCE_ID),
    investigation_id: str | None = Form(default=None),
) -> IngestJob:
    ingestion = service_or_503(container, "ingestion")
    limit = container.settings.max_upload_bytes

    buffer = bytearray()
    while chunk := await file.read(READ_CHUNK_BYTES):
        buffer.extend(chunk)
        if len(buffer) > limit:
            raise PayloadTooLarge(f"upload exceeds the {limit} byte limit")
    if not buffer:
        raise UploadRejected("the uploaded file is empty")

    try:
        job = await ingestion.ingest_upload(
            filename=file.filename or "upload.bin",
            data=bytes(buffer),
            source_id=source_id,
            permissions=[ctx.role.value, "admin"],
            investigation_id=investigation_id,
        )
    except ValueError as exc:
        raise UploadRejected(str(exc))

    # Processing continues in the background; the client polls or watches the stream.
    spawn(_process(ingestion, job.job_id), name=f"ingest:{job.job_id}")
    return job


async def _process(ingestion, job_id: str) -> None:
    from spectra_config.logging import get_logger

    try:
        await ingestion.process_job(job_id)
    except Exception as exc:  # pragma: no cover - the job records its own failure
        get_logger(__name__).error("upload.process_failed", job_id=job_id, error=str(exc))


@router.get("/uploads/{job_id}", response_model=IngestJob)
async def upload_status(job_id: str, container: Container, ctx: Ctx) -> IngestJob:
    job = await container.storage.repository.get_job(job_id)
    if job is None:
        raise NotFound(f"unknown job: {job_id!r}")
    return job


@router.get("/uploads", response_model=list[IngestJob])
async def list_uploads(container: Container, ctx: Ctx, limit: int = 50) -> list[IngestJob]:
    return await container.storage.repository.list_jobs(limit=limit)
