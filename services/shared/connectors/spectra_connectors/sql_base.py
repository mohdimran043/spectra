"""Shared SQL connector.

One class implements every capability the Database Agent needs; the dialect
subclasses (:mod:`postgres`, :mod:`mysql`, :mod:`sqlite`) only supply a URL, a
driver name and a dialect tag.

Read-only is enforced in four independent layers, because any one of them can be
bypassed by a clever statement:

1. :class:`SqlGuard` - only a single, allow-listed, row-capped ``SELECT`` parses.
2. :class:`ReadOnlySession` - statement timeout, client-side fetch cap, and a
   transaction that is always rolled back.
3. The **deployment contract** - the connection string must name a database role
   with ``SELECT``-only grants.  :meth:`SqlConnector.verify_read_only` proves
   (or disproves) that at runtime by attempting a no-op write that is rolled
   back, and reports whether the database itself refused it.
4. The **audit trail** - every ``query_readonly`` writes a row through
   ``repository.record_sql_audit`` whether it succeeded or failed.
"""

from __future__ import annotations

import asyncio
import importlib
import time
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any, ClassVar

from spectra_config import Settings, get_settings
from spectra_config.logging import get_logger
from spectra_schemas.catalog import SourceDescriptor, SourceHealth
from spectra_schemas.enums import AssetKind, SourceStatus
from spectra_schemas.provenance import DatabaseLocator
from spectra_schemas.security import SYSTEM, PermissionContext
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from .audit import AuditSink, RepositoryAuditSink, record_safely
from .base import DiscoveredItem, SourceConnector
from .credentials import CredentialStore
from .errors import ConfigurationError, ConnectionFailed, DriverUnavailable, PermissionDenied
from .sql_guard import GENERIC, SqlGuard, quote_identifier
from .sql_introspect import count_rows, describe_table, list_relationships, list_tables
from .sql_session import DEFAULT_BATCH_SIZE, ReadOnlySession
from .sql_types import (
    ColumnInfo,
    DatabaseRecord,
    EntityHit,
    EntityMapping,
    QueryResult,
    ReadOnlyProbe,
    Relationship,
    TableInfo,
    parse_entity_map,
)

log = get_logger(__name__)

#: Ceiling for the ingestion pipeline's full-table stream (overridable per source).
DEFAULT_STREAM_MAX_ROWS = 5_000_000
RUN_SQL_CAPABILITY = "run_sql"


class SqlConnector(SourceConnector):
    """Read-only relational source connector."""

    dialect: ClassVar[str] = GENERIC
    driver_module: ClassVar[str] = ""
    driver_package: ClassVar[str] = ""

    def __init__(
        self,
        descriptor: SourceDescriptor,
        credentials: CredentialStore | None = None,
        *,
        audit: AuditSink | None = None,
        settings: Settings | None = None,
    ) -> None:
        super().__init__(descriptor, credentials)
        self._settings = settings or get_settings()
        self._audit: AuditSink = audit or RepositoryAuditSink()
        self._engine: Engine | None = None
        self._tables: tuple[str, ...] | None = None
        self._lock = asyncio.Lock()
        self._schema: str | None = self.config("schema")
        self._configured_tables: tuple[str, ...] | None = _as_names(self.config("tables"))
        self._entity_mappings: tuple[EntityMapping, ...] = parse_entity_map(self.config("entity_map"))
        self._stream_max_rows = int(self.config("stream_max_rows", DEFAULT_STREAM_MAX_ROWS))

    # -- dialect hooks ----------------------------------------------------
    def _url(self) -> Any:
        """Build the SQLAlchemy URL.  Implemented by each dialect subclass."""
        raise NotImplementedError

    def _engine_kwargs(self) -> dict[str, Any]:
        return {"pool_pre_ping": True, "future": True}

    def _safe_url(self) -> str:
        url = self._url()
        render = getattr(url, "render_as_string", None)
        return render(hide_password=True) if render else str(url)

    def _require_driver(self) -> None:
        if not self.driver_module:
            return
        try:
            importlib.import_module(self.driver_module)
        except ImportError as exc:
            package = self.driver_package or self.driver_module
            raise DriverUnavailable(
                f"the {self.source_type.value} connector needs the {package!r} driver: pip install {package}"
            ) from exc

    # -- lifecycle --------------------------------------------------------
    async def connect(self) -> None:
        if self._engine is not None:
            return
        async with self._lock:
            if self._engine is not None:
                return
            self._require_driver()
            try:
                self._engine = await asyncio.to_thread(self._create_engine)
            except SQLAlchemyError as exc:
                raise ConnectionFailed(f"cannot connect to {self.source_id}: {exc}") from exc
            self._connected = True
            log.info(
                "sql.connected",
                source_id=self.source_id,
                dialect=self.dialect,
                url=self._safe_url(),
                connection=self.safe_connection(),
            )

    def _create_engine(self) -> Engine:
        return create_engine(self._url(), **self._engine_kwargs())

    async def close(self) -> None:
        engine, self._engine = self._engine, None
        self._tables = None
        self._connected = False
        if engine is not None:
            await asyncio.to_thread(engine.dispose)

    async def _require_engine(self) -> Engine:
        await self.connect()
        if self._engine is None:  # pragma: no cover - connect() raises first
            raise ConnectionFailed(f"source {self.source_id} is not connected")
        return self._engine

    async def _session(self) -> ReadOnlySession:
        return ReadOnlySession(
            await self._require_engine(),
            dialect=self.dialect,
            timeout_seconds=self._settings.sql_query_timeout_seconds,
            max_rows=self._settings.sql_max_rows,
        )

    # -- guard ------------------------------------------------------------
    async def guard(self, *, max_rows: int | None = None) -> SqlGuard:
        """A guard restricted to this source's allow-listed tables."""
        return SqlGuard(
            await self.get_tables(),
            max_rows=max_rows or self._settings.sql_max_rows,
            dialect=self.dialect,
        )

    # -- SourceConnector --------------------------------------------------
    async def validate(self) -> SourceHealth:
        started = time.perf_counter()
        try:
            tables = await self.get_tables()
        except Exception as exc:  # noqa: BLE001 - health must never raise
            log.warning("sql.validate_failed", source_id=self.source_id, error=str(exc))
            return self._health(SourceStatus.UNREACHABLE, detail=str(exc), started=started)
        if not tables:
            return self._health(
                SourceStatus.DEGRADED,
                detail="connected, but no tables are visible to this role",
                started=started,
            )
        return self._health(
            SourceStatus.HEALTHY,
            detail=f"{len(tables)} table(s) available",
            started=started,
            asset_count=len(tables),
        )

    async def discover(self) -> AsyncIterator[DiscoveredItem]:
        """Stream one item per allow-listed table (not per row)."""
        engine = await self._require_engine()
        for table in await self.get_tables():
            rows = await asyncio.to_thread(count_rows, engine, table, self._quote(table))
            self._record_checkpoint(table, added=1)
            yield DiscoveredItem(
                external_id=f"{self.source_id}:{table}",
                name=table,
                media_type="application/vnd.spectra.table+json",
                size=rows,
                kind=AssetKind.TABLE,
                extra={"table": table, "row_count": rows, "dialect": self.dialect},
            )

    async def fetch(self, item: DiscoveredItem) -> AsyncIterator[dict[str, Any]]:
        """Stream the rows of a discovered table."""
        table = str(item.extra.get("table") or item.name)
        async for batch in self.stream_rows(table):
            for row in batch:
                yield dict(row)

    async def metadata(self) -> dict[str, Any]:
        tables = await self.get_tables()
        return {
            "source_id": self.source_id,
            "type": self.source_type.value,
            "dialect": self.dialect,
            "url": self._safe_url(),
            "schema": self._schema,
            "tables": list(tables),
            "allow_list_configured": self._configured_tables is not None,
            "entity_map": [
                {"entity_type": m.entity_type, "table": m.table, "column": m.column}
                for m in self._entity_mappings
            ],
            "max_rows": self._settings.sql_max_rows,
            "timeout_seconds": self._settings.sql_query_timeout_seconds,
            "connection": self.safe_connection(),
        }

    # -- Database Agent capabilities --------------------------------------
    async def get_tables(self) -> tuple[str, ...]:
        """Allow-listed tables: the configured list intersected with reality."""
        if self._tables is not None:
            return self._tables
        engine = await self._require_engine()
        visible = await asyncio.to_thread(list_tables, engine, self._schema)
        if self._configured_tables is None:
            self._tables = visible
            return self._tables
        allowed = {name.lower() for name in self._configured_tables}
        self._tables = tuple(name for name in visible if name.lower() in allowed)
        missing = allowed - {name.lower() for name in visible}
        if missing:
            log.warning("sql.allowlist_missing_tables", source_id=self.source_id, tables=sorted(missing))
        return self._tables

    async def get_columns(self, table: str) -> tuple[ColumnInfo, ...]:
        info = await self._table_info(table)
        return info.columns

    async def get_relationships(self) -> tuple[Relationship, ...]:
        engine = await self._require_engine()
        tables = await self.get_tables()
        return await asyncio.to_thread(list_relationships, engine, tables, self._schema)

    async def get_schema(self) -> dict[str, Any]:
        """Whole-database description: tables, columns, keys and relationships."""
        tables = await self.get_tables()
        infos = [await self._table_info(table) for table in tables]
        relationships = await self.get_relationships()
        return {
            "source_id": self.source_id,
            "dialect": self.dialect,
            "schema": self._schema,
            "tables": {info.name: info.to_dict() for info in infos},
            "relationships": [relationship.to_dict() for relationship in relationships],
            "entity_map": [
                {"entity_type": m.entity_type, "table": m.table, "column": m.column}
                for m in self._entity_mappings
            ],
        }

    async def query_readonly(
        self,
        sql: str,
        params: Mapping[str, Any] | Sequence[Any] | None = None,
        ctx: PermissionContext | None = None,
    ) -> QueryResult:
        """Guard -> timeout+row cap -> audit.  Every path writes an audit row."""
        context = ctx or SYSTEM
        guard = await self.guard()
        validated = None
        try:
            self._assert_may_query(context)
            validated = guard.validate(sql, params)
            session = await self._session()
            result = await session.execute(validated)
        except Exception as exc:
            await self._write_audit(
                sql=validated.sql if validated else sql,
                params=validated.params if validated else _params_dict(params),
                user_id=context.user_id,
                rows=0,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
            )
            log.warning(
                "sql.query_rejected",
                source_id=self.source_id,
                user_id=context.user_id,
                reason=str(exc),
            )
            raise
        await self._write_audit(
            sql=validated.sql,
            params=validated.params,
            user_id=context.user_id,
            rows=result.row_count,
            ok=True,
            error=None,
        )
        return result

    async def get_record(
        self,
        table: str,
        primary_key: str,
        record_id: Any,
        ctx: PermissionContext | None = None,
    ) -> DatabaseRecord | None:
        """Fetch one row by primary key, with the locator that cites it."""
        guard = await self.guard()
        validated = guard.build_select(table, where={primary_key: record_id}, limit=1)
        result = await self.query_readonly(validated.sql, validated.params, ctx)
        if not result.rows:
            return None
        return DatabaseRecord(
            source_id=self.source_id,
            table=table,
            primary_key=primary_key,
            record_id=str(record_id),
            record=result.rows[0],
            locator=DatabaseLocator(
                source_id=self.source_id,
                table=table,
                primary_key=primary_key,
                record_id=str(record_id),
            ),
        )

    async def find_entity(
        self,
        entity_type: str,
        value: Any,
        ctx: PermissionContext | None = None,
        limit: int = 10,
    ) -> tuple[EntityHit, ...]:
        """Look ``value`` up in every table this source maps to ``entity_type``."""
        mappings = [m for m in self._entity_mappings if m.entity_type.lower() == entity_type.lower()]
        if not mappings:
            log.debug("sql.entity_type_unmapped", source_id=self.source_id, entity_type=entity_type)
            return ()
        tables = {name.lower() for name in await self.get_tables()}
        hits: list[EntityHit] = []
        for mapping in mappings:
            if mapping.table.lower() not in tables:
                log.warning("sql.entity_table_missing", source_id=self.source_id, table=mapping.table)
                continue
            hits.extend(await self._lookup(mapping, value, ctx, limit))
        return tuple(hits)

    async def _lookup(
        self,
        mapping: EntityMapping,
        value: Any,
        ctx: PermissionContext | None,
        limit: int,
    ) -> list[EntityHit]:
        guard = await self.guard()
        validated = guard.build_select(mapping.table, where={mapping.column: value}, limit=limit)
        result = await self.query_readonly(validated.sql, validated.params, ctx)
        primary_key = mapping.primary_key or await self._primary_key(mapping.table) or mapping.column
        return [
            EntityHit(
                source_id=self.source_id,
                entity_type=mapping.entity_type,
                table=mapping.table,
                column=mapping.column,
                value=str(value),
                record=row,
                label=None if not mapping.label_column else _text(row.get(mapping.label_column)),
                locator=DatabaseLocator(
                    source_id=self.source_id,
                    table=mapping.table,
                    primary_key=primary_key,
                    record_id=str(row.get(primary_key, value)),
                    column=mapping.column,
                ),
            )
            for row in result.rows
        ]

    async def stream_rows(
        self,
        table: str,
        batch_size: int = DEFAULT_BATCH_SIZE,
        ctx: PermissionContext | None = None,
    ) -> AsyncIterator[tuple[Mapping[str, Any], ...]]:
        """Stream a whole table in batches for the ingestion pipeline.

        This is the ingestion path, so the interactive ``sql_max_rows`` cap does
        not apply - ``stream_max_rows`` (default five million) does - but the
        statement still goes through the guard and the rows are never all held
        in memory at once.
        """
        self._assert_may_query(ctx or SYSTEM)
        guard = await self.guard(max_rows=self._stream_max_rows)
        validated = guard.build_select(table, limit=self._stream_max_rows)
        session = await self._session()
        async for batch in session.stream(validated, batch_size):
            yield batch

    async def verify_read_only(self) -> ReadOnlyProbe:
        """Probe whether the *database role* refuses writes (not just SPECTRA).

        Runs ``UPDATE <table> SET <col> = <col> WHERE 1 = 0`` inside a
        transaction that is rolled back: it changes nothing even when the role
        is over-privileged, and its failure is the proof we want.
        """
        tables = await self.get_tables()
        if not tables:
            raise ConfigurationError(f"source {self.source_id} exposes no tables to probe")
        table = tables[0]
        columns = await self.get_columns(table)
        if not columns:
            raise ConfigurationError(f"table {table!r} exposes no columns to probe")
        session = await self._session()
        return await session.verify_read_only(
            self.source_id, self._quote(table), self._quote(columns[0].name)
        )

    # -- helpers ----------------------------------------------------------
    async def _table_info(self, table: str) -> TableInfo:
        if table.lower() not in {name.lower() for name in await self.get_tables()}:
            raise PermissionDenied(f"table {table!r} is not in the allow-list for {self.source_id}")
        engine = await self._require_engine()
        return await asyncio.to_thread(describe_table, engine, table, self._schema)

    async def _primary_key(self, table: str) -> str | None:
        info = await self._table_info(table)
        return info.primary_key[0] if info.primary_key else None

    def _quote(self, name: str) -> str:
        return quote_identifier(name, self.dialect)

    def _assert_may_query(self, ctx: PermissionContext) -> None:
        if not ctx.can(RUN_SQL_CAPABILITY):
            raise PermissionDenied(f"role {ctx.role.value!r} may not run SQL")
        if not ctx.may_read_source(self.source_id, list(self._descriptor.permissions)):
            raise PermissionDenied(f"role {ctx.role.value!r} may not read source {self.source_id}")

    async def _write_audit(
        self,
        *,
        sql: str,
        params: Mapping[str, Any],
        user_id: str,
        rows: int,
        ok: bool,
        error: str | None,
    ) -> None:
        await record_safely(
            self._audit,
            source_id=self.source_id,
            sql=sql,
            params=params,
            user_id=user_id,
            rows=rows,
            ok=ok,
            error=error,
        )


def _as_names(value: Any) -> tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value)
    raise ConfigurationError(f"'tables' must be a list of table names, got {type(value).__name__}")


def _params_dict(params: Mapping[str, Any] | Sequence[Any] | None) -> dict[str, Any]:
    if params is None:
        return {}
    if isinstance(params, Mapping):
        return {str(key): value for key, value in params.items()}
    return {f"p{index}": value for index, value in enumerate(params)}


def _text(value: Any) -> str | None:
    return None if value is None else str(value)
