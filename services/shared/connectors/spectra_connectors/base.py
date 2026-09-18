"""The connector contract every SPECTRA source implements.

A connector is the *only* thing that knows how to talk to an external system.
Everything above it - ingestion, the Source Service, the Database Agent - sees
the same seven verbs, which is what lets a new source type (SharePoint, Drive,
Kafka) be added without touching agent code.

Streaming is a hard requirement
-------------------------------
``discover()`` returns an **async iterator** and must yield items as it finds
them.  A source with millions of rows or objects must never be materialised in
memory: no ``return [...]``, no ``list(...)`` of a full listing, no unbounded
buffering inside the connector.  Implementations page/walk the remote system and
``yield`` each :class:`DiscoveredItem` immediately, and record enough state in
:meth:`SourceConnector.checkpoint` that an interrupted sync resumes from the
last page instead of restarting.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, ClassVar

from spectra_schemas.catalog import SourceDescriptor, SourceHealth
from spectra_schemas.enums import AssetKind, SourceStatus, SourceType

from .credentials import CredentialStore, redact


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class DiscoveredItem:
    """One thing a source holds: a file, an object, a table, an API record.

    Immutable by construction - ``discover()`` yields new instances rather than
    mutating a shared cursor object.
    """

    external_id: str
    name: str
    media_type: str = "application/octet-stream"
    size: int = 0
    modified_at: datetime | None = None
    kind: AssetKind = AssetKind.DOCUMENT
    extra: Mapping[str, Any] = field(default_factory=dict)

    def with_extra(self, **values: Any) -> DiscoveredItem:
        """Return a copy with additional ``extra`` keys (never mutates self)."""
        return replace(self, extra={**dict(self.extra), **values})


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """Resumable position in a source's discovery stream.

    ``cursor`` is connector-defined and opaque to callers: a max mtime for a
    folder, a continuation token / last key for S3, a table+offset for SQL, a
    page token for a REST API.
    """

    cursor: str | None = None
    discovered_count: int = 0
    updated_at: datetime = field(default_factory=utcnow)

    def advance(self, cursor: str | None, *, added: int = 0) -> Checkpoint:
        """Return the next checkpoint - the old one is left untouched."""
        return Checkpoint(
            cursor=cursor,
            discovered_count=self.discovered_count + added,
            updated_at=utcnow(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cursor": self.cursor,
            "discovered_count": self.discovered_count,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> Checkpoint:
        if not payload:
            return cls()
        raw_updated = payload.get("updated_at")
        updated_at = utcnow()
        if isinstance(raw_updated, datetime):
            updated_at = raw_updated
        elif isinstance(raw_updated, str):
            try:
                updated_at = datetime.fromisoformat(raw_updated)
            except ValueError:
                updated_at = utcnow()
        cursor = payload.get("cursor")
        return cls(
            cursor=None if cursor is None else str(cursor),
            discovered_count=int(payload.get("discovered_count") or 0),
            updated_at=updated_at,
        )


class SourceConnector(ABC):
    """Abstract base for every source type.

    Lifecycle::

        connector = registry.create(descriptor)
        async with connector:                 # connect() / close()
            health = await connector.validate()
            async for item in connector.discover():
                payload = await connector.fetch(item)
    """

    source_type: ClassVar[SourceType]

    def __init__(
        self,
        descriptor: SourceDescriptor,
        credentials: CredentialStore | None = None,
    ) -> None:
        self._descriptor = descriptor
        self._credentials = credentials or CredentialStore()
        self._checkpoint = Checkpoint()
        self._connected = False

    # -- identity ---------------------------------------------------------
    @property
    def descriptor(self) -> SourceDescriptor:
        return self._descriptor

    @property
    def source_id(self) -> str:
        return self._descriptor.source_id

    @property
    def connection(self) -> Mapping[str, Any]:
        """Non-secret connection settings.  Secrets live in the credential store."""
        return dict(self._descriptor.connection)

    @property
    def credentials(self) -> CredentialStore:
        return self._credentials

    def config(self, key: str, default: Any = None) -> Any:
        return self._descriptor.connection.get(key, default)

    def safe_connection(self) -> dict[str, Any]:
        """Connection settings with any secret-looking value masked - log-safe."""
        return redact(self._descriptor.connection)

    # -- lifecycle --------------------------------------------------------
    @abstractmethod
    async def connect(self) -> None:
        """Establish (or lazily prepare) the underlying client/engine."""

    @abstractmethod
    async def validate(self) -> SourceHealth:
        """Cheap liveness probe.  Must never raise - return an unhealthy report."""

    @abstractmethod
    def discover(self) -> AsyncIterator[DiscoveredItem]:
        """Stream every item this source currently holds.

        Implementations are async generators and MUST stream (see module
        docstring): they page through the remote system and yield each item as
        it is seen.
        """

    @abstractmethod
    async def fetch(self, item: DiscoveredItem) -> bytes | AsyncIterator[dict[str, Any]]:
        """Return the item's payload: bytes for blobs, a row stream for tables."""

    @abstractmethod
    async def metadata(self) -> dict[str, Any]:
        """Describe the source for the catalog UI.  Never includes secrets."""

    async def checkpoint(self) -> Checkpoint:
        """Current resumable position."""
        return self._checkpoint

    async def restore(self, checkpoint: Checkpoint) -> None:
        """Resume from a checkpoint produced by :meth:`checkpoint`."""
        self._checkpoint = checkpoint

    async def close(self) -> None:
        """Release clients/connections.  Safe to call more than once."""
        self._connected = False

    # -- helpers for subclasses ------------------------------------------
    def _record_checkpoint(self, cursor: str | None, *, added: int = 0) -> Checkpoint:
        self._checkpoint = self._checkpoint.advance(cursor, added=added)
        return self._checkpoint

    def _health(
        self,
        status: SourceStatus,
        *,
        detail: str | None = None,
        started: float | None = None,
        asset_count: int = 0,
        record_count: int = 0,
    ) -> SourceHealth:
        latency = None if started is None else round((time.perf_counter() - started) * 1000, 3)
        return SourceHealth(
            source_id=self.source_id,
            status=status,
            detail=detail,
            latency_ms=latency,
            asset_count=asset_count,
            record_count=record_count,
        )

    async def __aenter__(self) -> SourceConnector:
        await self.connect()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} source_id={self.source_id!r} type={self.source_type.value}>"
