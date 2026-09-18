"""SPECTRA source connectors.

One contract (:class:`SourceConnector`) for every place SPECTRA reads from -
local folders, uploads, S3/MinIO, PostgreSQL, MySQL, SQLite and REST APIs - plus
the read-only SQL layer (:class:`SqlGuard`, :class:`ReadOnlySession`) the
Database Agent depends on.

Importing this package is cheap and never requires an optional driver: the
connector modules that need boto3, psycopg, PyMySQL or httpx are imported on
first attribute access (PEP 562) and by :class:`ConnectorRegistry` on first
``create()``.

Typical use::

    service = SourceService()
    report = await service.sync("case-files", ingestion.handle_item)
    hits = await service.database_lookup("customer", "C82731", ctx)
"""

from __future__ import annotations

import importlib
from typing import Any

from .base import Checkpoint, DiscoveredItem, SourceConnector
from .credentials import CredentialStore, redact, reject_inline_secrets
from .errors import (
    ConfigurationError,
    ConnectionFailed,
    ConnectorError,
    CredentialError,
    DriverUnavailable,
    PathTraversalError,
    PermissionDenied,
    QueryFailed,
    QueryTimeout,
    SourceNotFound,
    SqlGuardError,
    SsrfBlocked,
    UnsupportedSourceType,
)
from .media import classify, guess_media_type, kind_for_media_type
from .net_guard import assert_safe_url
from .registry import BUILTIN_CONNECTORS, ConnectorRegistry, default_registry
from .service import SourceService, SyncReport
from .sql_types import (
    ColumnInfo,
    DatabaseRecord,
    EntityHit,
    EntityMapping,
    QueryResult,
    ReadOnlyProbe,
    Relationship,
    TableInfo,
    ValidatedSql,
)

#: Attribute name -> module that defines it, imported on first access.
_LAZY_EXPORTS: dict[str, str] = {
    "LocalFolderConnector": "spectra_connectors.local_folder",
    "UploadConnector": "spectra_connectors.local_folder",
    "S3Connector": "spectra_connectors.s3",
    "RestApiConnector": "spectra_connectors.rest_api",
    "SqlConnector": "spectra_connectors.sql_base",
    "PostgresConnector": "spectra_connectors.postgres",
    "MySqlConnector": "spectra_connectors.mysql",
    "SqliteConnector": "spectra_connectors.sqlite",
    "SqlGuard": "spectra_connectors.sql_guard",
    "quote_identifier": "spectra_connectors.sql_guard",
    "ReadOnlySession": "spectra_connectors.sql_session",
    "AuditSink": "spectra_connectors.audit",
    "RepositoryAuditSink": "spectra_connectors.audit",
}

__all__ = [
    "BUILTIN_CONNECTORS",
    "AuditSink",
    "Checkpoint",
    "ColumnInfo",
    "ConfigurationError",
    "ConnectionFailed",
    "ConnectorError",
    "ConnectorRegistry",
    "CredentialError",
    "CredentialStore",
    "DatabaseRecord",
    "DiscoveredItem",
    "DriverUnavailable",
    "EntityHit",
    "EntityMapping",
    "LocalFolderConnector",
    "MySqlConnector",
    "PathTraversalError",
    "PermissionDenied",
    "PostgresConnector",
    "QueryFailed",
    "QueryResult",
    "QueryTimeout",
    "ReadOnlyProbe",
    "ReadOnlySession",
    "Relationship",
    "RepositoryAuditSink",
    "RestApiConnector",
    "S3Connector",
    "SourceConnector",
    "SourceNotFound",
    "SourceService",
    "SqlConnector",
    "SqlGuard",
    "SqlGuardError",
    "SqliteConnector",
    "SsrfBlocked",
    "SyncReport",
    "TableInfo",
    "UnsupportedSourceType",
    "UploadConnector",
    "ValidatedSql",
    "assert_safe_url",
    "classify",
    "default_registry",
    "guess_media_type",
    "kind_for_media_type",
    "quote_identifier",
    "redact",
    "reject_inline_secrets",
]


def __getattr__(name: str) -> Any:
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(module_name), name)


def __dir__() -> list[str]:
    return sorted(__all__)
