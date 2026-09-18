"""Source Service - CRUD, health and sync over the source catalog.

The service owns the :class:`SourceDescriptor` lifecycle and nothing else: it
never parses a file, never embeds anything and never imports the ingestion
package.  ``sync()`` takes the ingestion handler as an **injected callable**, so
the dependency points one way (ingestion -> connectors) and the two services can
be deployed apart.

Sync state (the resumable :class:`Checkpoint`) is persisted under the
service-managed ``connection['_checkpoint']`` key, which keeps it in the same
row as the descriptor without widening the frozen schema.
"""

from __future__ import annotations

import inspect
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from spectra_config import Settings, get_settings
from spectra_config.logging import get_logger
from spectra_schemas.catalog import SourceDescriptor, SourceHealth
from spectra_schemas.enums import SourceStatus, SourceType
from spectra_schemas.security import SYSTEM, PermissionContext

from .audit import AuditSink
from .base import Checkpoint, DiscoveredItem, SourceConnector
from .credentials import CredentialStore, redact, reject_inline_secrets
from .errors import PermissionDenied, SourceNotFound
from .registry import ConnectorRegistry, default_registry
from .sql_types import EntityHit

log = get_logger(__name__)

#: Where the resumable sync checkpoint is stored inside ``connection``.
CHECKPOINT_KEY = "_checkpoint"
#: Source types that answer :meth:`SourceService.database_lookup`.
SQL_SOURCE_TYPES = frozenset({SourceType.POSTGRES, SourceType.MYSQL, SourceType.SQLITE})
MANAGE_SOURCES_CAPABILITY = "manage_sources"

ItemHandler = Callable[[DiscoveredItem], Awaitable[None] | None]


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class SyncReport:
    """Outcome of one :meth:`SourceService.sync` run."""

    source_id: str
    discovered: int
    failed: int
    checkpoint: Checkpoint
    duration_ms: float
    status: SourceStatus
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "discovered": self.discovered,
            "failed": self.failed,
            "checkpoint": self.checkpoint.to_dict(),
            "duration_ms": self.duration_ms,
            "status": self.status.value,
            "error": self.error,
        }


class SourceService:
    """Catalog operations the API and the agents share."""

    def __init__(
        self,
        repository: Any | None = None,
        registry: ConnectorRegistry | None = None,
        credentials: CredentialStore | None = None,
        *,
        audit: AuditSink | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._repository = repository
        self._credentials = credentials or CredentialStore()
        self._registry = registry or default_registry(self._credentials, audit=audit)
        self._settings = settings or get_settings()

    @property
    def registry(self) -> ConnectorRegistry:
        return self._registry

    async def repository(self) -> Any:
        """The relational repository, resolved from storage on first use."""
        if self._repository is None:
            from spectra_storage.facade import get_storage

            storage = await get_storage(self._settings)
            self._repository = storage.repository
        return self._repository

    # -- CRUD -------------------------------------------------------------
    async def list_sources(self, ctx: PermissionContext | None = None) -> tuple[SourceDescriptor, ...]:
        repository = await self.repository()
        descriptors = await repository.list_sources()
        context = ctx or SYSTEM
        return tuple(
            descriptor
            for descriptor in descriptors
            if context.may_read_source(descriptor.source_id, list(descriptor.permissions))
        )

    async def get_source(
        self, source_id: str, ctx: PermissionContext | None = None
    ) -> SourceDescriptor:
        repository = await self.repository()
        descriptor = await repository.get_source(source_id)
        if descriptor is None:
            raise SourceNotFound(f"no source registered with id {source_id!r}")
        context = ctx or SYSTEM
        if not context.may_read_source(source_id, list(descriptor.permissions)):
            raise PermissionDenied(f"role {context.role.value!r} may not read source {source_id}")
        return descriptor

    async def create_source(
        self, descriptor: SourceDescriptor, ctx: PermissionContext | None = None
    ) -> SourceDescriptor:
        """Register a source after asserting it carries no inlined secrets."""
        self._assert_may_manage(ctx)
        reject_inline_secrets(descriptor.connection)
        self._registry.resolve(descriptor.type)
        repository = await self.repository()
        stored = await repository.upsert_source(descriptor)
        log.info(
            "source.created",
            source_id=stored.source_id,
            type=stored.type.value,
            connection=redact(stored.connection),
        )
        return stored

    async def update_source(
        self,
        source_id: str,
        changes: Mapping[str, Any],
        ctx: PermissionContext | None = None,
    ) -> SourceDescriptor:
        """Apply ``changes`` immutably (``model_copy``) and persist the result."""
        self._assert_may_manage(ctx)
        if "connection" in changes:
            reject_inline_secrets(dict(changes["connection"]))
        descriptor = await self.get_source(source_id, ctx)
        updated = descriptor.model_copy(update=dict(changes))
        repository = await self.repository()
        stored = await repository.upsert_source(updated)
        log.info("source.updated", source_id=source_id, fields=sorted(changes))
        return stored

    async def delete_source(self, source_id: str, ctx: PermissionContext | None = None) -> bool:
        self._assert_may_manage(ctx)
        repository = await self.repository()
        deleted = bool(await repository.delete_source(source_id))
        log.info("source.deleted", source_id=source_id, deleted=deleted)
        return deleted

    async def set_enabled(
        self, source_id: str, enabled: bool, ctx: PermissionContext | None = None
    ) -> SourceDescriptor:
        return await self.update_source(source_id, {"enabled": enabled}, ctx)

    # -- connectors -------------------------------------------------------
    async def connector(
        self, source_id: str, ctx: PermissionContext | None = None
    ) -> SourceConnector:
        """Build a connected connector for ``source_id`` (caller closes it)."""
        descriptor = await self.get_source(source_id, ctx)
        connector = self._registry.create(descriptor)
        await connector.connect()
        return connector

    async def health(self, source_id: str, ctx: PermissionContext | None = None) -> SourceHealth:
        descriptor = await self.get_source(source_id, ctx)
        health = await self._registry.health_check(descriptor)
        await self._persist_health(descriptor, health)
        return health

    async def health_all(self, ctx: PermissionContext | None = None) -> tuple[SourceHealth, ...]:
        descriptors = await self.list_sources(ctx)
        results = await self._registry.health_check_all(descriptors)
        for descriptor, health in zip(descriptors, results, strict=False):
            await self._persist_health(descriptor, health)
        return results

    async def _persist_health(self, descriptor: SourceDescriptor, health: SourceHealth) -> None:
        if descriptor.status is health.status and descriptor.status_detail == health.detail:
            return
        repository = await self.repository()
        await repository.upsert_source(
            descriptor.model_copy(update={"status": health.status, "status_detail": health.detail})
        )

    # -- sync -------------------------------------------------------------
    async def sync(
        self,
        source_id: str,
        on_item: ItemHandler,
        *,
        limit: int | None = None,
        resume: bool = True,
        ctx: PermissionContext | None = None,
    ) -> SyncReport:
        """Stream discovery into ``on_item`` - the ingestion service's handler.

        ``on_item`` may be sync or async.  Items are handed over one at a time as
        they are discovered, so a source with millions of records never lands in
        memory, and the checkpoint is persisted at the end so an interrupted run
        resumes instead of restarting.
        """
        descriptor = await self.get_source(source_id, ctx)
        connector = self._registry.create(descriptor)
        started = time.perf_counter()
        discovered, failed, checkpoint, error = await self._drain(
            connector, descriptor, on_item, limit=limit, resume=resume
        )
        if error is not None:
            log.error("source.sync_failed", source_id=source_id, discovered=discovered, error=error)
            status = SourceStatus.UNREACHABLE
        else:
            status = SourceStatus.DEGRADED if failed else SourceStatus.HEALTHY
            await self._persist_sync(descriptor, checkpoint, discovered, status)
            log.info("source.synced", source_id=source_id, discovered=discovered, failed=failed)
        return SyncReport(
            source_id=source_id,
            discovered=discovered,
            failed=failed,
            checkpoint=checkpoint,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            status=status,
            error=error,
        )

    async def _drain(
        self,
        connector: SourceConnector,
        descriptor: SourceDescriptor,
        on_item: ItemHandler,
        *,
        limit: int | None,
        resume: bool,
    ) -> tuple[int, int, Checkpoint, str | None]:
        """Run one discovery pass, returning counts, checkpoint and any failure."""
        discovered = failed = 0
        checkpoint = Checkpoint.from_dict(descriptor.connection.get(CHECKPOINT_KEY))
        try:
            async with connector:
                if resume:
                    await connector.restore(checkpoint)
                async for item in connector.discover():
                    discovered += 1
                    failed += await _handle(on_item, item, descriptor.source_id)
                    if limit is not None and discovered >= limit:
                        break
                checkpoint = await connector.checkpoint()
        except Exception as exc:  # noqa: BLE001 - reported in the SyncReport, not hidden
            return discovered, failed, checkpoint, f"{type(exc).__name__}: {exc}"
        return discovered, failed, checkpoint, None

    async def _persist_sync(
        self,
        descriptor: SourceDescriptor,
        checkpoint: Checkpoint,
        discovered: int,
        status: SourceStatus,
    ) -> None:
        repository = await self.repository()
        await repository.upsert_source(
            descriptor.model_copy(
                update={
                    "connection": {**descriptor.connection, CHECKPOINT_KEY: checkpoint.to_dict()},
                    "last_sync": _now(),
                    "asset_count": max(descriptor.asset_count, discovered),
                    "status": status,
                }
            )
        )

    # -- entity resolution ------------------------------------------------
    async def database_lookup(
        self,
        entity_type: str,
        value: Any,
        ctx: PermissionContext | None = None,
        *,
        limit: int = 10,
    ) -> tuple[EntityHit, ...]:
        """Ask every enabled SQL source whether it knows this entity."""
        descriptors = [
            descriptor
            for descriptor in await self.list_sources(ctx)
            if descriptor.enabled and descriptor.type in SQL_SOURCE_TYPES
        ]
        hits: list[EntityHit] = []
        for descriptor in descriptors:
            hits.extend(await self._lookup_one(descriptor, entity_type, value, ctx, limit))
        log.info(
            "source.database_lookup",
            entity_type=entity_type,
            sources=len(descriptors),
            hits=len(hits),
        )
        return tuple(hits)

    async def _lookup_one(
        self,
        descriptor: SourceDescriptor,
        entity_type: str,
        value: Any,
        ctx: PermissionContext | None,
        limit: int,
    ) -> Sequence[EntityHit]:
        connector = self._registry.create(descriptor)
        try:
            async with connector:
                finder = getattr(connector, "find_entity", None)
                if finder is None:
                    return ()
                return await finder(entity_type, value, ctx, limit)
        except Exception as exc:  # noqa: BLE001 - one bad source must not fail the lookup
            log.warning(
                "source.database_lookup_failed",
                source_id=descriptor.source_id,
                entity_type=entity_type,
                error=str(exc),
            )
            return ()

    # -- helpers ----------------------------------------------------------
    def _assert_may_manage(self, ctx: PermissionContext | None) -> None:
        context = ctx or SYSTEM
        if not context.can(MANAGE_SOURCES_CAPABILITY):
            raise PermissionDenied(f"role {context.role.value!r} may not manage sources")


async def _handle(on_item: ItemHandler, item: DiscoveredItem, source_id: str) -> int:
    """Run the injected handler; return 1 when it failed, 0 otherwise."""
    try:
        result = on_item(item)
        if inspect.isawaitable(result):
            await result
    except Exception as exc:  # noqa: BLE001 - one bad item must not stop the sync
        log.warning(
            "source.item_failed",
            source_id=source_id,
            external_id=item.external_id,
            error=str(exc),
        )
        return 1
    return 0
