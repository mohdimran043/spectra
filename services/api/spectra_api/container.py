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
    evidence: Any = None
    investigations: Any = None
    trace_broker: Any = None
    indexer: Any = None
    degraded: list[str] = field(default_factory=list)
    agent_overrides: dict[str, bool] = field(default_factory=dict)
    verified_records: dict[str, bool] = field(default_factory=dict)

    def note_degraded(self, reason: str) -> None:
        if reason not in self.degraded:
            self.degraded.append(reason)
            log.warning("container.degraded", reason=reason)

    def agent_flags(self) -> dict[str, bool]:
        """Configured flags with runtime Agent-Control-Center overrides applied."""
        flags = dict(self.settings.agent_flags())
        flags.update(self.agent_overrides)
        return flags

    def set_agent_flag(self, name: str, enabled: bool) -> dict[str, bool]:
        if name not in self.settings.agent_flags():
            raise KeyError(name)
        self.agent_overrides = {**self.agent_overrides, name: enabled}
        return self.agent_flags()


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

    # -- evidence ----------------------------------------------------------
    try:
        from spectra_evidence.graph import EvidenceGraph
        from spectra_evidence.service import EvidenceService

        evidence = EvidenceService(graph=EvidenceGraph(container.storage.graph), settings=settings)
        # Application links are only emitted for records that genuinely exist.
        if container.sources is not None:
            evidence = evidence.with_verifier(_record_verifier(container))
        container.evidence = evidence
    except Exception as exc:
        container.note_degraded(f"evidence service unavailable: {exc}")

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

    # -- agent / investigations -------------------------------------------
    # The Brain takes its peers by injection, so we hand it the services this
    # container already built rather than letting it construct a second set.
    try:
        from spectra_agent.context import AgentServices
        from spectra_agent.service import build_investigation_service
        from spectra_agent.streaming import TraceBroker

        container.trace_broker = TraceBroker()
        container.investigations = await build_investigation_service(
            settings,
            services=AgentServices(
                search=container.search,
                entities=container.entities,
                evidence=container.evidence,
                sources=container.sources,
                storage=container.storage,
                gateway=container.gateway,
            ),
            broker=container.trace_broker,
            flags_provider=container.agent_flags,
        )
        missing = container.investigations._services.missing()  # noqa: SLF001 - startup diagnostics
        if missing:
            container.note_degraded(f"agent running without: {', '.join(missing)}")
    except Exception as exc:
        container.note_degraded(f"investigation service unavailable: {exc}")
        log.error("container.agent_failed", error=str(exc), exc_info=True)

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


def _record_verifier(container: ServiceContainer):
    """Synchronous existence check used before an application deep link is emitted.

    The resolver is sync, so this consults the cache the source service populates
    rather than blocking on I/O; an unknown record simply yields no link.
    """

    def verify(entity_type: str, record_id: str) -> bool:
        cache = container.verified_records
        return bool(cache.get(f"{entity_type}:{record_id}"))

    return verify


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
        for name in ("investigations", "ingestion", "sources"):
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
