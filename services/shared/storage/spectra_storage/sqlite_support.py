"""Shared SQLite plumbing for the embedded vector / lexical / graph backends.

The embedded backends exist so a laptop install needs no infrastructure, but
they still run inside an asyncio service.  ``SqliteDatabase`` therefore keeps a
single connection, serialises access with an ``asyncio.Lock`` and executes the
blocking ``sqlite3`` work on a worker thread, which keeps the event loop free.
"""

from __future__ import annotations

import asyncio
import re
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from spectra_config.logging import get_logger

log = get_logger(__name__)

T = TypeVar("T")

BUSY_TIMEOUT_SECONDS = 30.0
_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")


class StorageIdentifierError(ValueError):
    """Raised when a collection / index name cannot be used as a SQL identifier."""


def safe_identifier(name: str) -> str:
    """Validate a caller-supplied collection or index name.

    SQL identifiers cannot be bound as parameters, so every name that reaches an
    ``CREATE TABLE``/``SELECT`` statement is validated against a strict allowlist
    first - this is the injection boundary for the embedded backends.
    """
    if not _IDENTIFIER_RE.match(name or ""):
        raise StorageIdentifierError(
            f"invalid storage identifier {name!r}: expected ^[A-Za-z][A-Za-z0-9_]{{0,62}}$"
        )
    return name


class SqliteDatabase:
    """Thread-offloaded, lock-serialised access to one SQLite file."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._connection: sqlite3.Connection | None = None

    @property
    def path(self) -> Path:
        return self._path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self._path), check_same_thread=False, timeout=BUSY_TIMEOUT_SECONDS
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _ensure(self) -> sqlite3.Connection:
        if self._connection is None:
            self._connection = self._connect()
            log.debug("sqlite.connected", path=str(self._path))
        return self._connection

    async def run(self, work: Callable[[sqlite3.Connection], T]) -> T:
        """Execute ``work`` against the connection on a worker thread."""
        async with self._lock:
            return await asyncio.to_thread(self._run_sync, work)

    def _run_sync(self, work: Callable[[sqlite3.Connection], T]) -> T:
        connection = self._ensure()
        try:
            result = work(connection)
        except sqlite3.Error:
            connection.rollback()
            raise
        connection.commit()
        return result

    async def close(self) -> None:
        async with self._lock:
            if self._connection is None:
                return
            connection, self._connection = self._connection, None
            await asyncio.to_thread(connection.close)
            log.debug("sqlite.closed", path=str(self._path))

    async def file_size_bytes(self) -> int:
        def _size(_: sqlite3.Connection) -> int:
            return self._path.stat().st_size if self._path.exists() else 0

        return await self.run(_size)


def fetch_all(connection: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    return list(connection.execute(sql, params).fetchall())


def fetch_one(connection: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
    return connection.execute(sql, params).fetchone()


def scalar(connection: sqlite3.Connection, sql: str, params: tuple[Any, ...] = (), default: int = 0) -> int:
    row = connection.execute(sql, params).fetchone()
    if row is None or row[0] is None:
        return default
    return int(row[0])
