"""Connector error taxonomy.

Every failure a connector can produce is one of these, so callers (the Source
Service, the Database Agent, the API layer) branch on an exception *type* rather
than on message text.  Messages are safe to surface to an operator: they never
contain credentials because every value that reaches them is passed through
:func:`spectra_connectors.credentials.redact` first.
"""

from __future__ import annotations


class ConnectorError(Exception):
    """Base class for every connector failure."""


class ConfigurationError(ConnectorError):
    """The ``SourceDescriptor.connection`` payload is missing or invalid."""


class CredentialError(ConnectorError):
    """A credential reference could not be resolved, or a secret was inlined."""


class ConnectionFailed(ConnectorError):
    """The remote system could not be reached or refused the connection."""


class DriverUnavailable(ConnectorError):
    """An optional driver (boto3 / psycopg / PyMySQL) is not installed."""


class PathTraversalError(ConnectorError):
    """A discovered or requested path escaped the configured root."""


class SsrfBlocked(ConnectorError):
    """A request target resolved to a private, loopback or metadata address."""


class SqlGuardError(ConnectorError):
    """A statement was rejected by :class:`~spectra_connectors.sql_guard.SqlGuard`."""


class QueryTimeout(ConnectorError):
    """A read-only query exceeded ``settings.sql_query_timeout_seconds``."""


class QueryFailed(ConnectorError):
    """The database rejected a guarded read-only query (syntax, type, missing column)."""


class PermissionDenied(ConnectorError):
    """The :class:`PermissionContext` does not allow this operation."""


class SourceNotFound(ConnectorError):
    """No source is registered under the requested id."""


class UnsupportedSourceType(ConnectorError):
    """No connector class is registered for the requested :class:`SourceType`."""
