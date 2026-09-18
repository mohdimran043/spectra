"""MySQL / MariaDB source connector.

Same contract as the PostgreSQL connector: non-secret settings in
``connection``, the password behind ``credential_ref``, and a database role that
only holds ``SELECT`` grants.  The statement timeout is applied as
``SET SESSION max_execution_time`` (MySQL) with a ``max_statement_time``
fallback (MariaDB) - see :mod:`spectra_connectors.sql_session`.
"""

from __future__ import annotations

from typing import Any, ClassVar

from spectra_schemas.enums import SourceType
from sqlalchemy.engine import URL

from .errors import ConfigurationError
from .sql_base import SqlConnector
from .sql_guard import MYSQL

DEFAULT_PORT = 3306
DEFAULT_CHARSET = "utf8mb4"
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10


class MySqlConnector(SqlConnector):
    """Read-only MySQL/MariaDB connector (PyMySQL, imported lazily)."""

    source_type: ClassVar[SourceType] = SourceType.MYSQL
    dialect: ClassVar[str] = MYSQL
    driver_module: ClassVar[str] = "pymysql"
    driver_package: ClassVar[str] = "PyMySQL"

    def _url(self) -> URL:
        database = self.config("database")
        if not database:
            raise ConfigurationError("mysql source requires connection['database']")
        secret = self._credentials.resolve(self._descriptor.credential_ref)
        query = {str(key): str(value) for key, value in dict(self.config("options") or {}).items()}
        query.setdefault("charset", str(self.config("charset") or DEFAULT_CHARSET))
        return URL.create(
            "mysql+pymysql",
            username=secret.get("username") or self.config("user") or "root",
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
            "connect_args": {"connect_timeout": DEFAULT_CONNECT_TIMEOUT_SECONDS},
        }
