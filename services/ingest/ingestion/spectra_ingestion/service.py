"""IngestionService - the public face of the ingestion pipeline.

The API layer and the worker only ever call this class.  It owns upload
security, the asset catalogue, the job status machine and pipeline routing;
the expensive work happens here, at ingestion time, and never at query time.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

from spectra_ai_core.gateway import ModelGateway, get_gateway
from spectra_ai_core.phase import ingestion_phase
from spectra_config import Settings, get_settings
from spectra_config.logging import get_logger
from spectra_schemas import (
    Asset,
    AssetKind,
    IngestJob,
    JobStatus,
    asset_id,
    content_hash,
    object_uri,
)
from spectra_schemas import (
    job_id as new_job_id,
)
from spectra_storage.facade import Storage, get_storage

from .entity_hook import EntityExtractor
from .indexer import Indexer, IndexReport
from .pipelines.audio import AudioPipeline
from .pipelines.base import (
    STAGE_EMBED,
    STAGE_EXTRACT,
    STAGE_INDEX,
    BasePipeline,
    IngestResult,
    JobContext,
    StageReporter,
)
from .pipelines.database import DatabasePipeline, RowSource, TableSchema
from .pipelines.document import DocumentPipeline
from .pipelines.image import ImagePipeline
from .pipelines.video import VideoPipeline
from .security import UploadRejected, job_directory, scan_for_malware, staged_path, validate_upload

log = get_logger(__name__)

TABLE_MEDIA_TYPE: Final[str] = "application/vnd.spectra.table"
DEFAULT_PERMISSIONS: Final[tuple[str, ...]] = ("admin", "analyst", "viewer")
TERMINAL_STATUSES: Final[frozenset[JobStatus]] = frozenset({JobStatus.READY, JobStatus.FAILED})
STAGE_STATUS: Final[dict[str, JobStatus]] = {
    STAGE_EXTRACT: JobStatus.EXTRACTING,
    STAGE_EMBED: JobStatus.EMBEDDING,
    STAGE_INDEX: JobStatus.EMBEDDING,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class IngestionService:
    """Accepts sources, enforces upload security and drives ingestion jobs."""

    def __init__(
        self,
        storage: Storage,
        gateway: ModelGateway,
        indexer: Indexer,
        *,
        settings: Settings | None = None,
        entity_extractor: EntityExtractor | None = None,
    ) -> None:
        self._storage = storage
        self._gateway = gateway
        self._indexer = indexer
        self._settings = settings or storage.settings or get_settings()
        self._pipelines: dict[AssetKind, BasePipeline] = _build_pipelines(indexer, gateway, entity_extractor)
        self._payloads: dict[str, Mapping[str, Any]] = {}
        self._live: dict[str, IngestJob] = {}
        self._tasks: dict[str, asyncio.Task[IngestJob]] = {}

    @classmethod
    async def create(cls, *, entity_extractor: EntityExtractor | None = None) -> IngestionService:
        storage = await get_storage()
        gateway = await get_gateway()
        return cls(storage, gateway, Indexer(storage, gateway), entity_extractor=entity_extractor)

    # -- public API -------------------------------------------------------
    async def ingest_upload(
        self,
        filename: str,
        data: bytes,
        source_id: str,
        permissions: Sequence[str] | None = None,
    ) -> IngestJob:
        """Validate, stage and queue an uploaded file.  Returns immediately."""
        upload = validate_upload(filename, data, self._settings)
        job = await self._create_job(source_id)
        target = staged_path(self._settings, job.job_id, upload.filename)
        try:
            await asyncio.to_thread(_write_private, target, data)
            await scan_for_malware(self._settings.antivirus_hook, target)
        except UploadRejected:
            await asyncio.to_thread(_remove, target)
            await self._fail(job, "upload rejected by security checks")
            raise

        existing = await self._find_duplicate(upload.content_hash)
        if existing is not None:
            await asyncio.to_thread(_remove, target)
            return await self._complete_duplicate(job, existing)

        asset = _build_asset(
            source_id=source_id,
            title=upload.filename,
            kind=upload.kind,
            media_type=upload.media_type,
            digest=upload.content_hash,
            size_bytes=upload.size_bytes,
            extension=upload.extension,
            permissions=permissions,
            staged=target,
        )
        await self._store_object(asset, data)
        return await self._queue(job, asset)

    async def ingest_path(
        self, path: str | Path, source_id: str, *, permissions: Sequence[str] | None = None
    ) -> IngestJob:
        """Ingest a file already on disk (local-folder connector, demo corpus)."""
        source = Path(path)
        if not source.is_file():
            raise FileNotFoundError(f"{source} is not a file")
        data = await asyncio.to_thread(source.read_bytes)
        return await self.ingest_upload(source.name, data, source_id, permissions)

    async def ingest_rows(
        self,
        source_id: str,
        schema: TableSchema,
        rows: RowSource,
        *,
        title: str | None = None,
        permissions: Sequence[str] | None = None,
    ) -> IngestJob:
        """Queue a connector-provided row stream for the database pipeline."""
        job = await self._create_job(source_id)
        digest = content_hash(f"{source_id}:{schema.table}".encode())
        asset = _build_asset(
            source_id=source_id,
            title=title or schema.table,
            kind=AssetKind.TABLE,
            media_type=TABLE_MEDIA_TYPE,
            digest=digest,
            size_bytes=0,
            extension="",
            permissions=permissions,
            staged=None,
            uri=f"spectra://tables/{source_id}/{schema.table}",
        )
        self._payloads[job.job_id] = {"rows": rows, "schema": schema}
        return await self._queue(job, asset)

    async def process_job(self, job_id: str) -> IngestJob:
        """Drive one job through QUEUED -> ... -> READY (or FAILED).

        Runs inside the ingestion phase, which is what permits OCR, transcription
        and vision captioning: they are paid for here, once per object, and never
        again on the query path.
        """
        async with ingestion_phase():
            return await self._process_job(job_id)

    async def _process_job(self, job_id: str) -> IngestJob:
        job = await self._storage.repository.get_job(job_id)
        if job is None:
            raise KeyError(f"unknown job {job_id}")
        asset = await self._storage.repository.get_asset(job.asset_id or "")
        if asset is None:
            return await self._fail(job, f"job {job_id} has no asset to process")

        try:
            job = await self._advance(job, JobStatus.PROCESSING, "processing", 0.05)
            result = await self._run_pipeline(job, asset)
        except Exception as exc:
            log.warning("ingest.job_failed", job_id=job_id, asset_id=asset.asset_id, error=str(exc))
            await self._mark_asset_failed(asset, str(exc))
            return await self._fail(job, str(exc))

        job = await self._advance(job, JobStatus.INDEXED, "indexed", 0.9, f"{result.chunk_count} chunks")
        await self._storage.repository.upsert_asset(
            result.asset.model_copy(
                update={"status": JobStatus.READY, "ingested_at": _now(), "error": None}
            )
        )
        message = _summary(result)
        return await self._advance(job, JobStatus.READY, "ready", 1.0, message)

    async def progress(self, job_id: str) -> dict[str, Any]:
        """Job state for the UI - never raises for an unknown id."""
        job = await self._storage.repository.get_job(job_id)
        if job is None:
            return {"job_id": job_id, "status": "unknown", "progress": 0.0}
        return {
            "job_id": job.job_id,
            "asset_id": job.asset_id,
            "source_id": job.source_id,
            "status": job.status.value,
            "stage": job.stage,
            "progress": round(job.progress, 3),
            "message": job.message,
            "error": job.error,
            "stages_completed": list(job.stages_completed),
            "updated_at": job.updated_at.isoformat(),
        }

    async def wait_for_job(self, job_id: str, timeout: float | None = None) -> IngestJob:
        """Await the background task for a job (used by the worker and tests)."""
        task = self._tasks.get(job_id)
        if task is not None:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        job = await self._storage.repository.get_job(job_id)
        if job is None:
            raise KeyError(f"unknown job {job_id}")
        return job

    async def reindex(self, asset_ids: Sequence[str] | None = None) -> list[IndexReport]:
        return await self._indexer.reindex(asset_ids)

    # -- internals --------------------------------------------------------
    async def _run_pipeline(self, job: IngestJob, asset: Asset) -> IngestResult:
        pipeline = self._pipelines.get(asset.kind)
        if pipeline is None:
            raise ValueError(f"no pipeline for asset kind {asset.kind.value}")
        context = JobContext(
            job_id=job.job_id,
            source_id=job.source_id,
            local_path=await self._materialise(asset),
            permissions=tuple(asset.permissions),
            payload=self._payloads.pop(job.job_id, {}),
            report=self._reporter(job),
        )
        job = await self._advance(job, JobStatus.EXTRACTING, STAGE_EXTRACT, 0.15, "extracting content")
        return await pipeline.run(asset, context)

    def _reporter(self, job: IngestJob) -> StageReporter:
        """Progress callback handed to the pipeline; stages drive the status machine."""

        async def report(stage: str, progress: float, message: str = "") -> None:
            await self._advance(job, STAGE_STATUS.get(stage, JobStatus.PROCESSING), stage, progress, message)

        return report

    async def _materialise(self, asset: Asset) -> Path | None:
        if asset.kind is AssetKind.TABLE:
            return None
        staged = asset.metadata.get("staged_path")
        if staged and Path(staged).exists():
            return Path(staged)
        try:
            local = await self._storage.objects.local_path(asset.object_uri)
        except Exception as exc:
            raise FileNotFoundError(f"cannot materialise {asset.object_uri}: {exc}") from exc
        if not Path(local).exists():
            raise FileNotFoundError(f"object {asset.object_uri} is not available locally")
        return Path(local)

    async def _create_job(self, source_id: str) -> IngestJob:
        job = IngestJob(job_id=new_job_id(), source_id=source_id, status=JobStatus.QUEUED, stage="queued")
        await self._storage.repository.upsert_job(job)
        return job

    async def _queue(self, job: IngestJob, asset: Asset) -> IngestJob:
        await self._storage.repository.upsert_asset(asset)
        queued = await self._advance(
            job.model_copy(update={"asset_id": asset.asset_id}),
            JobStatus.QUEUED,
            "queued",
            0.01,
            f"queued {asset.title}",
        )
        task = asyncio.create_task(self.process_job(queued.job_id))
        self._tasks[queued.job_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(queued.job_id, None))
        return queued

    async def _find_duplicate(self, digest: str) -> Asset | None:
        try:
            return await self._storage.repository.find_asset_by_hash(digest)
        except Exception as exc:
            log.warning("ingest.dedupe_lookup_failed", error=str(exc))
            return None

    async def _complete_duplicate(self, job: IngestJob, existing: Asset) -> IngestJob:
        log.info("ingest.duplicate", asset_id=existing.asset_id, content_hash=existing.content_hash)
        self._payloads.pop(job.job_id, None)
        return await self._advance(
            job.model_copy(update={"asset_id": existing.asset_id}),
            JobStatus.READY,
            "deduplicated",
            1.0,
            f"identical content already ingested as {existing.asset_id}",
        )

    async def _store_object(self, asset: Asset, data: bytes) -> None:
        try:
            await self._storage.objects.put(asset.object_uri, data, asset.media_type)
        except Exception as exc:
            log.warning("ingest.object_store_failed", asset_id=asset.asset_id, error=str(exc))

    async def _advance(
        self,
        job: IngestJob,
        status: JobStatus,
        stage: str,
        progress: float,
        message: str | None = None,
        error: str | None = None,
    ) -> IngestJob:
        """Record one transition of the job status machine.

        The live copy is authoritative, so a caller holding an older snapshot
        (a pipeline progress callback, say) cannot drop stages already recorded.
        """
        current = self._live.get(job.job_id, job)
        stages = (
            current.stages_completed
            if stage in current.stages_completed
            else [*current.stages_completed, stage]
        )
        updated = current.model_copy(
            update={
                "status": status,
                "stage": stage,
                "progress": max(0.0, min(progress, 1.0)),
                "message": message,
                "error": error,
                "updated_at": _now(),
                "stages_completed": stages,
            }
        )
        if status in TERMINAL_STATUSES:
            self._live.pop(updated.job_id, None)
        else:
            self._live[updated.job_id] = updated
        try:
            await self._storage.repository.upsert_job(updated)
        except Exception as exc:  # the job must keep running even if its record does not
            log.warning("ingest.job_persist_failed", job_id=job.job_id, error=str(exc))
        return updated

    async def _fail(self, job: IngestJob, error: str) -> IngestJob:
        self._payloads.pop(job.job_id, None)
        return await self._advance(job, JobStatus.FAILED, "failed", 1.0, "ingestion failed", error)

    async def _mark_asset_failed(self, asset: Asset, error: str) -> None:
        try:
            await self._storage.repository.upsert_asset(
                asset.model_copy(update={"status": JobStatus.FAILED, "error": error})
            )
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("ingest.asset_status_failed", asset_id=asset.asset_id, error=str(exc))

    def cleanup_job_files(self, job_id: str) -> None:
        """Remove the isolated upload directory of a finished job."""
        directory = job_directory(self._settings, job_id)
        for child in sorted(directory.glob("*")):
            _remove(child)
        try:
            directory.rmdir()
        except OSError as exc:
            log.warning("ingest.cleanup_failed", job_id=job_id, error=str(exc))


def _build_pipelines(
    indexer: Indexer, gateway: ModelGateway, entity_extractor: EntityExtractor | None
) -> dict[AssetKind, BasePipeline]:
    return {
        AssetKind.DOCUMENT: DocumentPipeline(indexer, gateway, entity_extractor=entity_extractor),
        AssetKind.IMAGE: ImagePipeline(indexer, gateway, entity_extractor=entity_extractor),
        AssetKind.AUDIO: AudioPipeline(indexer, gateway, entity_extractor=entity_extractor),
        AssetKind.VIDEO: VideoPipeline(indexer, gateway, entity_extractor=entity_extractor),
        AssetKind.TABLE: DatabasePipeline(indexer, gateway, entity_extractor=entity_extractor),
    }


def _build_asset(
    *,
    source_id: str,
    title: str,
    kind: AssetKind,
    media_type: str,
    digest: str,
    size_bytes: int,
    extension: str,
    permissions: Sequence[str] | None,
    staged: Path | None,
    uri: str | None = None,
) -> Asset:
    metadata = {"staged_path": str(staged)} if staged is not None else {}
    return Asset(
        asset_id=asset_id(source_id, digest),
        source_id=source_id,
        kind=kind,
        title=title,
        object_uri=uri or object_uri(digest, extension),
        media_type=media_type,
        size_bytes=size_bytes,
        content_hash=digest,
        status=JobStatus.QUEUED,
        metadata=metadata,
        permissions=list(permissions or DEFAULT_PERMISSIONS),
    )


def _summary(result: IngestResult) -> str:
    warnings = f", {len(result.warnings)} warnings" if result.warnings else ""
    return f"{result.chunk_count} chunks, {result.image_vector_count} image vectors{warnings}"


def _write_private(target: Path, data: bytes) -> None:
    target.write_bytes(data)
    target.chmod(0o600)


def _remove(target: Path) -> None:
    try:
        target.unlink(missing_ok=True)
    except OSError as exc:  # pragma: no cover - defensive
        log.warning("ingest.remove_failed", path=str(target), error=str(exc))
