"""Connector registry - the extension seam.

Extension contract
------------------
A new source type (SharePoint, OneDrive, Google Drive, Elasticsearch, Kafka, a
message queue, another object store) is added **without touching the agent, the
ingestion pipeline or the API**:

1. Subclass :class:`~spectra_connectors.base.SourceConnector`, set the
   ``source_type`` class attribute and implement ``connect``, ``validate``,
   ``discover`` (streaming!), ``fetch``, ``metadata`` and ``close``.  Resolve
   secrets through the injected :class:`CredentialStore` - never from
   ``descriptor.connection``.
2. Register it::

       registry.register(SourceType.SHAREPOINT, SharePointConnector)

   or, for a lazily imported third-party driver, register the import path
   ``"my_package.sharepoint:SharePointConnector"`` so the module is only
   imported when a source of that type is actually created.
3. Nothing else changes: ``SourceService.sync`` already streams discovery into
   ingestion, ``health_check_all`` already probes it, and the Brain still sees
   one catalog.

Registration is copy-on-write - :meth:`ConnectorRegistry.register` rebuilds the
factory mapping rather than mutating it, so a registry snapshot handed to
another component cannot change underneath it.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
from collections.abc import Mapping, Sequence
from typing import Any

from spectra_config.logging import get_logger
from spectra_schemas.catalog import SourceDescriptor, SourceHealth
from spectra_schemas.enums import SourceStatus, SourceType

from .audit import AuditSink
from .base import SourceConnector
from .credentials import CredentialStore
from .errors import ConfigurationError, UnsupportedSourceType

log = get_logger(__name__)

#: Built-ins are recorded as import paths so ``import spectra_connectors`` never
#: pulls in boto3 / psycopg / PyMySQL.  They load on first ``create()``.
BUILTIN_CONNECTORS: Mapping[SourceType, str] = {
    SourceType.LOCAL_FOLDER: "spectra_connectors.local_folder:LocalFolderConnector",
    SourceType.UPLOAD: "spectra_connectors.local_folder:UploadConnector",
    SourceType.S3: "spectra_connectors.s3:S3Connector",
    SourceType.POSTGRES: "spectra_connectors.postgres:PostgresConnector",
    SourceType.MYSQL: "spectra_connectors.mysql:MySqlConnector",
    SourceType.SQLITE: "spectra_connectors.sqlite:SqliteConnector",
    SourceType.REST_API: "spectra_connectors.rest_api:RestApiConnector",
}

#: How many sources are probed at once by :meth:`ConnectorRegistry.health_check_all`.
HEALTH_CONCURRENCY = 8

Factory = type[SourceConnector] | str


class ConnectorRegistry:
    """Maps :class:`SourceType` to a connector class."""

    def __init__(
        self,
        credentials: CredentialStore | None = None,
        *,
        factories: Mapping[SourceType, Factory] | None = None,
        audit: AuditSink | None = None,
    ) -> None:
        self._credentials = credentials or CredentialStore()
        self._factories: Mapping[SourceType, Factory] = dict(
            factories if factories is not None else BUILTIN_CONNECTORS
        )
        self._audit = audit

    @property
    def credentials(self) -> CredentialStore:
        return self._credentials

    def supported(self) -> tuple[SourceType, ...]:
        return tuple(sorted(self._factories, key=lambda item: item.value))

    def supports(self, source_type: SourceType) -> bool:
        return source_type in self._factories

    def register(self, source_type: SourceType, connector: Factory) -> None:
        """Add or replace a connector class (copy-on-write)."""
        if not isinstance(connector, str) and not (
            inspect.isclass(connector) and issubclass(connector, SourceConnector)
        ):
            raise ConfigurationError(
                f"connector for {source_type.value!r} must be a SourceConnector subclass or an import path"
            )
        self._factories = {**self._factories, source_type: connector}
        log.info("connector.registered", source_type=source_type.value, connector=_label(connector))

    def resolve(self, source_type: SourceType) -> type[SourceConnector]:
        """Return (importing if needed) the class registered for ``source_type``."""
        factory = self._factories.get(source_type)
        if factory is None:
            raise UnsupportedSourceType(
                f"no connector registered for source type {source_type.value!r}; "
                f"registered: {', '.join(t.value for t in self.supported())}"
            )
        return factory if not isinstance(factory, str) else _import(factory)

    def create(self, descriptor: SourceDescriptor) -> SourceConnector:
        """Build a connector for ``descriptor`` with credentials injected."""
        connector_cls = self.resolve(descriptor.type)
        return connector_cls(descriptor, self._credentials, **self._extra_kwargs(connector_cls))

    def _extra_kwargs(self, connector_cls: type[SourceConnector]) -> dict[str, Any]:
        if self._audit is None:
            return {}
        parameters = inspect.signature(connector_cls.__init__).parameters
        return {"audit": self._audit} if "audit" in parameters else {}

    async def health_check_all(
        self, descriptors: Sequence[SourceDescriptor]
    ) -> tuple[SourceHealth, ...]:
        """Probe every descriptor concurrently; one bad source never fails the rest."""
        semaphore = asyncio.Semaphore(HEALTH_CONCURRENCY)

        async def _probe(descriptor: SourceDescriptor) -> SourceHealth:
            async with semaphore:
                return await self.health_check(descriptor)

        return tuple(await asyncio.gather(*(_probe(item) for item in descriptors)))

    async def health_check(self, descriptor: SourceDescriptor) -> SourceHealth:
        """Probe one descriptor, converting any failure into an unhealthy report."""
        if not descriptor.enabled:
            return SourceHealth(
                source_id=descriptor.source_id,
                status=SourceStatus.UNCONFIGURED,
                detail="source is disabled",
            )
        connector: SourceConnector | None = None
        try:
            connector = self.create(descriptor)
            await connector.connect()
            return await connector.validate()
        except Exception as exc:  # noqa: BLE001 - health must never raise
            log.warning("connector.health_failed", source_id=descriptor.source_id, error=str(exc))
            return SourceHealth(
                source_id=descriptor.source_id,
                status=SourceStatus.UNREACHABLE,
                detail=f"{type(exc).__name__}: {exc}",
            )
        finally:
            if connector is not None:
                await _close_quietly(connector)


async def _close_quietly(connector: SourceConnector) -> None:
    try:
        await connector.close()
    except Exception as exc:  # noqa: BLE001 - closing must not mask the result
        log.warning("connector.close_failed", source_id=connector.source_id, error=str(exc))


def _import(path: str) -> type[SourceConnector]:
    module_name, _, attribute = path.partition(":")
    if not module_name or not attribute:
        raise ConfigurationError(f"connector path must look like 'module:Class', got {path!r}")
    try:
        module = importlib.import_module(module_name)
        connector_cls = getattr(module, attribute)
    except (ImportError, AttributeError) as exc:
        raise UnsupportedSourceType(f"cannot load connector {path!r}: {exc}") from exc
    if not (inspect.isclass(connector_cls) and issubclass(connector_cls, SourceConnector)):
        raise ConfigurationError(f"{path!r} is not a SourceConnector subclass")
    return connector_cls


def _label(connector: Factory) -> str:
    return connector if isinstance(connector, str) else connector.__name__


def default_registry(
    credentials: CredentialStore | None = None,
    *,
    audit: AuditSink | None = None,
) -> ConnectorRegistry:
    """A registry holding every built-in connector."""
    return ConnectorRegistry(credentials, audit=audit)
