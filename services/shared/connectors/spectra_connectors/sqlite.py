"""SQLite source connector.

``connection`` example::

    {"path": "/data/sources/crm.db", "read_only": true,
     "tables": ["customers", "transactions"],
     "entity_map": {"customer": {"table": "customers", "column": "customer_id"}}}

SQLite has no roles, so "read-only role" is expressed by opening the file with
the ``file:...?mode=ro`` URI (the default).  That makes
:meth:`SqlConnector.verify_read_only` genuinely meaningful here: the driver
itself refuses the probe write.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import quote

from spectra_schemas.enums import SourceType

from .errors import ConfigurationError
from .sql_base import SqlConnector
from .sql_guard import SQLITE


class SqliteConnector(SqlConnector):
    """Read-only SQLite connector (stdlib ``sqlite3``)."""

    source_type: ClassVar[SourceType] = SourceType.SQLITE
    dialect: ClassVar[str] = SQLITE

    @property
    def database_path(self) -> Path:
        raw = self.config("path")
        if not raw:
            raise ConfigurationError("sqlite source requires connection['path']")
        return Path(str(raw)).expanduser().resolve()

    @property
    def read_only(self) -> bool:
        return bool(self.config("read_only", True))

    def _url(self) -> str:
        path = self.database_path
        if not path.exists():
            raise ConfigurationError(f"sqlite database not found: {path}")
        if not self.read_only:
            return f"sqlite:///{path}"
        return f"sqlite:///file:{quote(str(path))}?mode=ro&uri=true"

    def _safe_url(self) -> str:
        return self._url()

    def _engine_kwargs(self) -> dict[str, Any]:
        # Queries run on worker threads, so the connection must not be pinned to
        # the creating thread; access is still serialised by SQLite itself.
        return {
            **super()._engine_kwargs(),
            "connect_args": {"check_same_thread": False, "timeout": 30.0},
        }
