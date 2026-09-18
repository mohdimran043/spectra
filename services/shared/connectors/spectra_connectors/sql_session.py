"""Runtime half of the read-only SQL contract.

:class:`SqlGuard` decides *what* may run; :class:`ReadOnlySession` decides *how*
it runs:

* every statement executes inside a transaction that is **always rolled back**,
  so even a mis-guarded statement cannot commit;
* a **server-side statement timeout** is applied in the database's own dialect -
  PostgreSQL ``SET LOCAL statement_timeout``, MySQL ``SET SESSION
  max_execution_time`` (MariaDB: ``max_statement_time``), SQLite a
  ``set_progress_handler`` interrupt - with an ``asyncio`` deadline on top as a
  backstop for a driver that ignores it;
* results are fetched with ``fetchmany(max_rows + 1)`` so a runaway query is
  **capped in the client too**, and the extra row is what sets ``truncated``.

SQLAlchemy's *synchronous* engine is used on a worker thread rather than an
async driver, because that is the one code path that works for psycopg, PyMySQL
and sqlite3 alike.  ``asyncio.to_thread`` cannot kill a thread, so the
database-side timeout is the real enforcement and the asyncio deadline only
bounds the caller's wait.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from spectra_config.logging import get_logger
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from .errors import ConnectionFailed, ConnectorError, QueryFailed, QueryTimeout
from .sql_types import QueryResult, ReadOnlyProbe, ValidatedSql

log = get_logger(__name__)

POSTGRES = "postgres"
MYSQL = "mysql"
SQLITE = "sqlite"

#: Extra seconds the asyncio deadline allows on top of the server-side timeout.
TIMEOUT_GRACE_SECONDS = 2.0
#: How often (in VM instructions) SQLite checks the deadline.
SQLITE_PROGRESS_INSTRUCTIONS = 1000
DEFAULT_BATCH_SIZE = 500
_MAX_PROBE_DETAIL = 400
#: Driver messages that mean "the statement timeout fired", per dialect.
_TIMEOUT_MARKERS = (
    "interrupted",  # sqlite3 progress-handler abort
    "statement timeout",  # PostgreSQL
    "canceling statement",  # PostgreSQL
    "query execution was interrupted",  # MySQL max_execution_time
    "max_statement_time exceeded",  # MariaDB
    "timeout",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _coerce(value: Any) -> Any:
    """Make a driver value JSON-friendly without losing precision silently."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, memoryview):
        return bytes(value).hex()
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).hex()
    return value


class ReadOnlySession:
    """Executes :class:`ValidatedSql` against one engine, read-only and bounded."""

    def __init__(
        self,
        engine: Engine,
        *,
        dialect: str,
        timeout_seconds: int,
        max_rows: int,
    ) -> None:
        self._engine = engine
        self._dialect = dialect
        self._timeout_seconds = int(timeout_seconds)
        self._max_rows = int(max_rows)

    @property
    def max_rows(self) -> int:
        return self._max_rows

    @property
    def timeout_seconds(self) -> int:
        return self._timeout_seconds

    # -- execution --------------------------------------------------------
    async def execute(self, validated: ValidatedSql) -> QueryResult:
        """Run a validated statement and return at most ``max_rows`` rows."""
        cap = min(validated.limit or self._max_rows, self._max_rows)
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._execute_blocking, validated, cap),
                timeout=self._timeout_seconds + TIMEOUT_GRACE_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            raise QueryTimeout(
                f"query exceeded {self._timeout_seconds}s statement timeout"
            ) from exc

    def _execute_blocking(self, validated: ValidatedSql, cap: int) -> QueryResult:
        started = time.perf_counter()
        try:
            with self._engine.connect() as connection:
                with self._statement_timeout(connection, self._timeout_seconds):
                    result = connection.execute(text(validated.sql), dict(validated.params))
                    columns = tuple(str(name) for name in result.keys())
                    fetched = result.fetchmany(cap + 1)
                connection.rollback()
        except SQLAlchemyError as exc:
            raise self._translate(exc) from exc
        truncated = len(fetched) > cap
        rows = tuple(
            {column: _coerce(value) for column, value in zip(columns, row, strict=False)} for row in fetched[:cap]
        )
        return QueryResult(
            columns=columns,
            rows=rows,
            sql=validated.sql,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
            truncated=truncated,
            row_limit=cap,
        )

    def _translate(self, exc: SQLAlchemyError) -> ConnectorError:
        """Turn a driver error into the connector taxonomy.

        A statement killed by the server-side timeout surfaces as an ordinary
        driver error, so it is recognised by message and re-raised as
        :class:`QueryTimeout` - callers should not have to parse driver text.
        """
        message = str(exc).lower()
        if any(marker in message for marker in _TIMEOUT_MARKERS):
            return QueryTimeout(
                f"query exceeded the {self._timeout_seconds}s statement timeout ({self._dialect})"
            )
        return QueryFailed(str(exc).strip().splitlines()[0])

    async def stream(
        self,
        validated: ValidatedSql,
        batch_size: int = DEFAULT_BATCH_SIZE,
        *,
        apply_timeout: bool = False,
    ) -> AsyncIterator[tuple[Mapping[str, Any], ...]]:
        """Yield batches of rows without materialising the whole result set.

        Used by the ingestion pipeline, which legitimately reads whole tables:
        the statement timeout is therefore off by default (the LIMIT baked into
        ``validated.sql`` is the bound), and rows are handed over in batches so
        memory stays flat.
        """
        size = max(1, int(batch_size))
        state = await asyncio.to_thread(self._open_stream, validated, apply_timeout)
        try:
            while True:
                batch = await asyncio.to_thread(self._fetch_batch, state, size)
                if not batch:
                    return
                yield batch
        finally:
            await asyncio.to_thread(self._close_stream, state)

    def _open_stream(self, validated: ValidatedSql, apply_timeout: bool) -> dict[str, Any]:
        connection = self._engine.connect().execution_options(
            stream_results=True, yield_per=DEFAULT_BATCH_SIZE
        )
        try:
            if apply_timeout:
                self._apply_timeout(connection, self._timeout_seconds)
            result = connection.execute(text(validated.sql), dict(validated.params))
        except SQLAlchemyError as exc:
            connection.close()
            raise self._translate(exc) from exc
        return {"connection": connection, "result": result, "columns": tuple(result.keys())}

    @staticmethod
    def _fetch_batch(state: Mapping[str, Any], size: int) -> tuple[Mapping[str, Any], ...]:
        columns = state["columns"]
        rows = state["result"].fetchmany(size)
        return tuple(
            {str(column): _coerce(value) for column, value in zip(columns, row, strict=False)} for row in rows
        )

    def _close_stream(self, state: Mapping[str, Any]) -> None:
        connection: Connection = state["connection"]
        try:
            connection.rollback()
        except SQLAlchemyError as exc:  # pragma: no cover - defensive
            log.warning("sql.stream_rollback_failed", dialect=self._dialect, error=str(exc))
        finally:
            connection.close()

    # -- read-only proof --------------------------------------------------
    async def verify_read_only(self, source_id: str, table: str, column: str) -> ReadOnlyProbe:
        """Attempt a no-op write inside a rolled-back transaction.

        ``WHERE 1 = 0`` means the statement touches no rows even if the role can
        write, and the transaction is rolled back either way - the point is only
        to learn whether the *database* refuses it.
        """
        probe_sql = f"UPDATE {table} SET {column} = {column} WHERE 1 = 0"
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._probe_blocking, source_id, probe_sql),
                timeout=self._timeout_seconds + TIMEOUT_GRACE_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            raise QueryTimeout("read-only probe timed out") from exc

    def _probe_blocking(self, source_id: str, probe_sql: str) -> ReadOnlyProbe:
        try:
            connection = self._engine.connect()
        except SQLAlchemyError as exc:
            raise ConnectionFailed(f"cannot open a connection for the read-only probe: {exc}") from exc
        try:
            connection.execute(text(probe_sql))
            enforced, detail = False, (
                "the configured role executed a write statement - it is NOT a read-only role; "
                "SPECTRA blocked the write itself, but the deployment must supply a read-only role"
            )
        except SQLAlchemyError as exc:
            enforced, detail = True, f"database refused the write: {str(exc).strip()[:_MAX_PROBE_DETAIL]}"
        finally:
            try:
                connection.rollback()
            finally:
                connection.close()
        log.info("sql.read_only_probe", source_id=source_id, enforced=enforced)
        return ReadOnlyProbe(
            source_id=source_id,
            enforced=enforced,
            detail=detail,
            probe=probe_sql,
            checked_at=_now(),
        )

    # -- timeout plumbing -------------------------------------------------
    @contextmanager
    def _statement_timeout(self, connection: Connection, seconds: int) -> Iterator[None]:
        cleanup = self._apply_timeout(connection, seconds)
        try:
            yield
        finally:
            if cleanup is not None:
                cleanup()

    def _apply_timeout(self, connection: Connection, seconds: int):
        """Apply a server-side timeout; return a cleanup callable when needed."""
        milliseconds = max(1, int(seconds * 1000))
        if self._dialect == POSTGRES:
            connection.exec_driver_sql(f"SET LOCAL statement_timeout = {milliseconds}")
            return None
        if self._dialect == MYSQL:
            self._apply_mysql_timeout(connection, milliseconds, seconds)
            return None
        if self._dialect == SQLITE:
            return self._apply_sqlite_timeout(connection, seconds)
        log.debug("sql.timeout_not_supported", dialect=self._dialect)
        return None

    @staticmethod
    def _apply_mysql_timeout(connection: Connection, milliseconds: int, seconds: int) -> None:
        try:
            connection.exec_driver_sql(f"SET SESSION max_execution_time = {milliseconds}")
        except SQLAlchemyError:
            # MariaDB spells it differently and takes seconds.
            connection.exec_driver_sql(f"SET SESSION max_statement_time = {seconds}")

    @staticmethod
    def _apply_sqlite_timeout(connection: Connection, seconds: int):
        driver = getattr(connection.connection, "driver_connection", connection.connection)
        handler = getattr(driver, "set_progress_handler", None)
        if handler is None:  # pragma: no cover - non-sqlite3 driver
            return None
        deadline = time.monotonic() + seconds

        def _interrupt() -> int:
            return 1 if time.monotonic() > deadline else 0

        handler(_interrupt, SQLITE_PROGRESS_INSTRUCTIONS)
        return lambda: handler(None, 0)


def normalise_rows(rows: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    """Public helper for callers that build rows outside a session."""
    return tuple({str(key): _coerce(value) for key, value in row.items()} for row in rows)
