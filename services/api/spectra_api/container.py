"""Service container - the one place where SPECTRA's services are wired together.

Construction is lazy and fault-tolerant: a service whose dependency is
unavailable is recorded as degraded rather than preventing the API from
starting.  The health endpoint then tells the operator exactly what is missing.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from spectra_config import Settings, get_settings
from spectra_config.logging import get_logger

log = get_logger(__name__)


@dataclass
class ServiceContainer:
    """Holds every long-lived service object for the process."""

    settings: Settings
    storage: Any = None
    gateway: Any = None
    sources: Any = None
    ingestion: Any = None
    search: Any = None
    entities: Any = None
    indexer: Any = None
    degraded: list[str] = field(default_factory=list)
    verified_records: dict[str, bool] = field(default_factory=dict)

    def note_degraded(self, reason: str) -> None:
        if reason not in self.degraded:
            self.degraded.append(reason)
            log.warning("container.degraded", reason=reason)


_container: ServiceContainer | None = None
_lock = asyncio.Lock()


async def build_container(settings: Settings | None = None) -> ServiceContainer:
    """Construct every service.  Each step degrades independently."""
    settings = settings or get_settings()
    container = ServiceContainer(settings=settings)

    # -- storage (required; the embedded backends have no external deps) ----
    from spectra_storage import get_storage

    container.storage = await get_storage(settings)

    # -- model gateway -----------------------------------------------------
    try:
        from spectra_ai_core import get_gateway

        container.gateway = await get_gateway(settings)
        for reason in container.gateway.degraded_reasons():
            container.note_degraded(f"models: {reason}")
    except Exception as exc:
        container.note_degraded(f"model gateway unavailable: {exc}")
        log.error("container.gateway_failed", error=str(exc), exc_info=True)

    # -- connectors / sources ---------------------------------------------
    try:
        from spectra_connectors.service import SourceService

        container.sources = SourceService(
            repository=container.storage.repository, settings=settings
        )
    except Exception as exc:
        container.note_degraded(f"source service unavailable: {exc}")

    # -- entity resolution -------------------------------------------------
    try:
        from spectra_entity_resolution.service import EntityResolutionService

        db_lookup = container.sources.database_lookup if container.sources else None
        container.entities = EntityResolutionService(
            storage=container.storage, gateway=container.gateway, settings=settings, db_lookup=db_lookup
        )
    except Exception as exc:
        container.note_degraded(f"entity resolution unavailable: {exc}")

    # -- search ------------------------------------------------------------
    try:
        from spectra_search.service import SearchService

        container.search = SearchService(
            storage=container.storage, gateway=container.gateway, settings=settings
        )
    except Exception as exc:
        container.note_degraded(f"search unavailable: {exc}")

    # -- ingestion ---------------------------------------------------------
    try:
        from spectra_ingestion import IngestionService
        from spectra_ingestion.indexer import Indexer

        from .adapters import ingestion_extractor_for

        indexer = Indexer(container.storage, container.gateway)
        container.indexer = indexer
        container.ingestion = IngestionService(
            container.storage,
            container.gateway,
            indexer,
            settings=settings,
            entity_extractor=ingestion_extractor_for(container.entities),
        )
    except Exception as exc:
        container.note_degraded(f"ingestion unavailable: {exc}")

    await _ensure_builtin_sources(container)

    log.info(
        "container.ready",
        degraded=len(container.degraded),
        backends=_describe_backends(settings),
    )
    return container


# Sources SPECTRA always has, regardless of what an operator configured.
BUILTIN_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("src_uploads", "Direct Uploads", "upload"),
    ("src_demo", "Demo Dataset", "local_folder"),
)


async def _ensure_builtin_sources(container: ServiceContainer) -> None:
    """Register the built-in sources so uploads have a real registry entry.

    Without this an uploaded asset points at a source id the Source Registry has
    never heard of, and reliability scoring silently falls back to a default
    with no inspectable reason.
    """
    from spectra_schemas import SourceDescriptor, SourceStatus, SourceType

    repository = container.storage.repository
    try:
        existing = {s.source_id for s in await repository.list_sources()}
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("container.source_bootstrap_failed", error=str(exc))
        return

    for source_id, name, kind in BUILTIN_SOURCES:
        if source_id in existing:
            continue
        await repository.upsert_source(
            SourceDescriptor(
                source_id=source_id,
                name=name,
                type=SourceType(kind),
                status=SourceStatus.HEALTHY,
                status_detail="built-in source",
            )
        )
        log.info("container.source_registered", source_id=source_id)


def _describe_backends(settings: Settings) -> dict[str, str]:
    return {
        "relational": settings.relational_backend.value,
        "vector": settings.vector_backend.value,
        "lexical": settings.lexical_backend.value,
        "graph": settings.graph_backend.value,
        "object": settings.object_backend.value,
        "cache": settings.cache_backend.value,
    }


async def get_container() -> ServiceContainer:
    global _container
    if _container is not None:
        return _container
    async with _lock:
        if _container is None:
            _container = await build_container()
    return _container


async def shutdown_container() -> None:
    global _container
    async with _lock:
        if _container is None:
            return
        for name in ("ingestion", "sources"):
            service = getattr(_container, name, None)
            close = getattr(service, "close", None)
            if close is not None:
                try:
                    await close()
                except Exception as exc:  # pragma: no cover - defensive
                    log.warning("container.close_failed", service=name, error=str(exc))
        if _container.gateway is not None:
            from spectra_ai_core import reset_gateway

            await reset_gateway()
        from spectra_storage import reset_storage

        await reset_storage()
        _container = None
