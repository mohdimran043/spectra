"""PostgreSQL source connector.

``connection`` carries only non-secret settings::

    {"host": "db", "port": 5432, "database": "crm", "user": "spectra_ro",
     "schema": "public", "tables": ["customers", "transactions"],
     "entity_map": {"customer": {"table": "customers", "column": "customer_id"}},
     "options": {"sslmode": "require"}}

The password is resolved from ``credential_ref`` through the
:class:`~spectra_connectors.credentials.CredentialStore` - never from
``connection``.  **The deployment must point this at a role with SELECT-only
grants**; :meth:`SqlConnector.verify_read_only` reports whether it really is.
"""

from __future__ import annotations

from typing import Any, ClassVar

from spectra_schemas.enums import SourceType
from sqlalchemy.engine import URL

from .errors import ConfigurationError
from .sql_base import SqlConnector
from .sql_guard import POSTGRES

DEFAULT_PORT = 5432
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10


class PostgresConnector(SqlConnector):
    """Read-only PostgreSQL connector (psycopg 3, imported lazily)."""

    source_type: ClassVar[SourceType] = SourceType.POSTGRES
    dialect: ClassVar[str] = POSTGRES
    driver_module: ClassVar[str] = "psycopg"
    driver_package: ClassVar[str] = "psycopg[binary]"

    def _url(self) -> URL:
        database = self.config("database")
        if not database:
            raise ConfigurationError("postgres source requires connection['database']")
        secret = self._credentials.resolve(self._descriptor.credential_ref)
        query = {str(key): str(value) for key, value in dict(self.config("options") or {}).items()}
        query.setdefault("connect_timeout", str(DEFAULT_CONNECT_TIMEOUT_SECONDS))
        query.setdefault("application_name", "spectra")
        return URL.create(
            "postgresql+psycopg",
            username=secret.get("username") or self.config("user") or "postgres",
            password=secret.get("password") or secret.get("value"),
            host=str(self.config("host") or "localhost"),
            port=int(self.config("port") or DEFAULT_PORT),
            database=str(database),
            query=query,
        )

    def _engine_kwargs(self) -> dict[str, Any]:
        return {
            **super()._engine_kwargs(),
            "pool_size": int(self.config("pool_size", 5)),
            "max_overflow": int(self.config("max_overflow", 2)),
            "pool_recycle": int(self.config("pool_recycle", 1800)),
        }
