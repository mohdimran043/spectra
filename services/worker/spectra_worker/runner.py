"""Background worker: drains queued ingest jobs and runs periodic maintenance.

Deliberately simple and pull-based so it scales horizontally - several workers can
run against the same control plane without coordination beyond the job claim.
"""

from __future__ import annotations

import asyncio
import signal
from dataclasses import dataclass

from spectra_config import Settings, get_settings
from spectra_config.logging import configure_logging, get_logger
from spectra_schemas import JobStatus

log = get_logger(__name__)

POLL_INTERVAL_SECONDS = 2.0
HEALTH_INTERVAL_SECONDS = 60.0
MAX_CONCURRENT_JOBS = 2


@dataclass
class WorkerStats:
    processed: int = 0
    failed: int = 0


class Worker:
    """Polls for queued ingest jobs and processes them with bounded concurrency."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.stats = WorkerStats()
        self._stopping = asyncio.Event()
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
        self._container = None

    async def start(self) -> None:
        from spectra_api.container import build_container

        self._container = await build_container(self.settings)
        log.info("worker.started", degraded=self._container.degraded)
        await asyncio.gather(self._job_loop(), self._health_loop())

    def stop(self) -> None:
        log.info("worker.stopping")
        self._stopping.set()

    async def _job_loop(self) -> None:
        while not self._stopping.is_set():
            try:
                await self._drain_once()
            except Exception as exc:
                log.error("worker.loop_error", error=str(exc), exc_info=True)
            await self._sleep(POLL_INTERVAL_SECONDS)

    async def _drain_once(self) -> None:
        container = self._container
        if container is None or container.ingestion is None:
            return
        jobs = await container.storage.repository.list_jobs(limit=25)
        queued = [j for j in jobs if j.status is JobStatus.QUEUED]
        if not queued:
            return
        await asyncio.gather(*(self._process(job.job_id) for job in queued), return_exceptions=True)

    async def _process(self, job_id: str) -> None:
        async with self._semaphore:
            container = self._container
            if container is None or container.ingestion is None:
                return
            try:
                await container.ingestion.process_job(job_id)
                self.stats.processed += 1
                log.info("worker.job_done", job_id=job_id, processed=self.stats.processed)
            except Exception as exc:
                self.stats.failed += 1
                log.error("worker.job_failed", job_id=job_id, error=str(exc))

    async def _health_loop(self) -> None:
        while not self._stopping.is_set():
            await self._sleep(HEALTH_INTERVAL_SECONDS)
            container = self._container
            if container is None:
                continue
            try:
                report = await container.storage.health()
                unhealthy = [k for k, v in report.items() if v.get("status") != "ok"]
                if unhealthy:
                    log.warning("worker.health_degraded", components=unhealthy)
            except Exception as exc:
                log.error("worker.health_failed", error=str(exc))

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stopping.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            return


async def run_worker() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    worker = Worker(settings)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, worker.stop)
        except NotImplementedError:  # pragma: no cover - non-POSIX
            pass

    try:
        await worker.start()
    finally:
        from spectra_api.container import shutdown_container

        await shutdown_container()
        log.info("worker.stopped", processed=worker.stats.processed, failed=worker.stats.failed)
