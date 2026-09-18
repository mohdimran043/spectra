"""Database Agent tools - exact lookup, read-only SQL, schema and single records."""

from __future__ import annotations

import re
from typing import Any

from spectra_schemas import AgentName, ToolError, ToolResult, ToolSpec

from ...context import ToolContext
from ...evidence_adapter import evidence_from_records, maybe_await
from ...tools.base import Tool, require_service
from ...tools.payloads import evidence_payload
from ...tools.schemas import EVIDENCE_OUTPUT, RECORDS_OUTPUT, integer, obj, string

# SQL is the one tool that can touch arbitrary data, so it is read-only, single
# statement, capped, and gated on the caller's `run_sql` capability.
SQL_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|merge|call)\b", re.I
)
DEFAULT_ROW_LIMIT = 50
MAX_ROW_LIMIT = 500
DB_TIMEOUT_SECONDS = 15.0


CONNECTOR_ATTRIBUTES = ("get_connector", "connector", "default_connector")
# What makes an object a SQL connector rather than the service that owns one.
CONNECTOR_METHODS = ("query_readonly", "get_schema", "get_record", "find_entity")


async def connector_for(ctx: ToolContext, tool: str, source_id: str | None) -> Any:
    """Resolve the SQL connector for ``source_id``, or the deployment's only one."""
    sources = require_service(ctx, "sources", tool)
    for attribute in CONNECTOR_ATTRIBUTES:
        connector = await _connector_from(sources, attribute, source_id)
        if connector is not None and any(hasattr(connector, m) for m in CONNECTOR_METHODS):
            return connector
    return sources


async def _connector_from(sources: Any, attribute: str, source_id: str | None) -> Any:
    candidate = getattr(sources, attribute, None)
    if candidate is None:
        return None
    if not callable(candidate):
        return candidate
    for call_args in ((source_id,), ()) if source_id else ((),):
        try:
            return await maybe_await(candidate(*call_args))
        except TypeError:
            continue
    return None


class QueryDatabaseTool(Tool):
    spec = ToolSpec(
        name="query_database",
        description=(
            "Look a value up in the enterprise systems of record, either by entity "
            "type and value (preferred) or with a single read-only SELECT statement."
        ),
        agent=AgentName.DATABASE,
        input_schema=obj(
            {
                "entity_type": string("Entity type to look up, e.g. transaction, customer, incident"),
                "value": string("Identifier or value to match"),
                "sql": string("A single read-only SELECT statement"),
                "source_id": string("Restrict the lookup to one source"),
                "limit": integer("Maximum rows", default=DEFAULT_ROW_LIMIT, minimum=1, maximum=MAX_ROW_LIMIT),
            }
        ),
        output_schema=EVIDENCE_OUTPUT,
        timeout_seconds=DB_TIMEOUT_SECONDS,
        requires_flag="database",
        cost_hint=0.5,
    )

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        sql = (args.get("sql") or "").strip()
        value = (args.get("value") or "").strip()
        if not sql and not value:
            raise ToolError(self.spec.name, "provide either 'value' (with 'entity_type') or 'sql'")
        if sql:
            rows, meta = await self._run_sql(ctx, sql, int(args.get("limit", DEFAULT_ROW_LIMIT)), args.get("source_id"))
        else:
            rows, meta = await self._lookup(ctx, args.get("entity_type") or "entity", value, args.get("source_id"))
        if not rows:
            return self.empty(f"no records matched {value or 'the query'}")
        items = await evidence_from_records(
            rows[: int(args.get("limit", DEFAULT_ROW_LIMIT))],
            source_id=meta["source_id"],
            table=meta["table"],
            primary_key=meta["primary_key"],
            retrieved_by=self.spec.name,
            services=ctx.services.evidence,
        )
        payload = evidence_payload(items)
        payload["records"] = rows[: int(args.get("limit", DEFAULT_ROW_LIMIT))]
        return self.success(
            data=payload,
            summary=f"{len(rows)} record(s) from {meta['source_id']}.{meta['table']}",
            count=len(items),
            evidence_ids=[item.evidence_id for item in items],
        )

    async def _lookup(
        self, ctx: ToolContext, entity_type: str, value: str, source_id: str | None
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        sources = require_service(ctx, "sources", self.spec.name)
        lookup = getattr(sources, "database_lookup", None)
        if lookup is not None:
            return _normalise_rows(await maybe_await(lookup(entity_type, value)), source_id, entity_type)
        connector = await connector_for(ctx, self.spec.name, source_id)
        find_entity = getattr(connector, "find_entity", None)
        if find_entity is None:
            raise ToolError(self.spec.name, "no database lookup entry point is available")
        return _normalise_rows(await maybe_await(find_entity(entity_type, value)), source_id, entity_type)

    async def _run_sql(
        self, ctx: ToolContext, sql: str, limit: int, source_id: str | None
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        if not ctx.permissions.can("run_sql"):
            raise ToolError(self.spec.name, f"role '{ctx.permissions.role.value}' may not run SQL")
        _assert_read_only(self.spec.name, sql)
        connector = await connector_for(ctx, self.spec.name, source_id)
        query_readonly = getattr(connector, "query_readonly", None)
        if query_readonly is None:
            raise ToolError(self.spec.name, "this source does not expose read-only SQL")
        rows, meta = _normalise_rows(
            await maybe_await(query_readonly(sql)), source_id, _table_from_sql(sql)
        )
        return rows[:limit], meta


def _assert_read_only(tool: str, sql: str) -> None:
    if ";" in sql.rstrip().rstrip(";"):
        raise ToolError(tool, "only a single statement may be executed")
    if not sql.lstrip().lower().startswith(("select", "with")):
        raise ToolError(tool, "only SELECT statements are permitted")
    forbidden = SQL_FORBIDDEN.search(sql)
    if forbidden:
        raise ToolError(tool, f"statement contains the forbidden keyword '{forbidden.group(0)}'")


def _table_from_sql(sql: str) -> str:
    match = re.search(r"\bfrom\s+([A-Za-z_][A-Za-z0-9_.]*)", sql, re.I)
    return match.group(1) if match else "query_result"


def _normalise_rows(
    payload: Any, source_id: str | None, table_hint: str
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Accept either a plain row list or a {source_id, table, rows} envelope."""
    meta = {"source_id": source_id or "database", "table": table_hint, "primary_key": "id"}
    if isinstance(payload, dict):
        meta["source_id"] = str(payload.get("source_id") or meta["source_id"])
        meta["table"] = str(payload.get("table") or meta["table"])
        meta["primary_key"] = str(payload.get("primary_key") or meta["primary_key"])
        payload = payload.get("rows") or payload.get("records") or []
    rows = [dict(row) for row in (payload or []) if isinstance(row, dict)]
    if rows and meta["primary_key"] not in rows[0]:
        meta["primary_key"] = next(
            (key for key in rows[0] if key.endswith("_id") or key == "id"), next(iter(rows[0]), "id")
        )
    return rows, meta


class GetDatabaseSchemaTool(Tool):
    spec = ToolSpec(
        name="get_database_schema",
        description="Describe a connected database: tables, columns and relationships.",
        agent=AgentName.DATABASE,
        input_schema=obj({"source_id": string("Source id of the database")}),
        output_schema=obj({"schema": {"type": "object", "description": "Tables, columns, relationships"}}),
        timeout_seconds=DB_TIMEOUT_SECONDS,
        requires_flag="database",
        cost_hint=0.3,
    )

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        connector = await connector_for(ctx, self.spec.name, args.get("source_id"))
        get_schema = getattr(connector, "get_schema", None)
        schema = await maybe_await(get_schema()) if get_schema else await self._compose(connector)
        if not schema:
            return self.empty("no schema is exposed by this source")
        tables = schema.get("tables") if isinstance(schema, dict) else None
        return self.success(
            data={"schema": schema if isinstance(schema, dict) else {"tables": schema}},
            summary=f"schema with {len(tables or [])} table(s)",
            count=len(tables or []),
        )

    async def _compose(self, connector: Any) -> dict[str, Any]:
        get_tables = getattr(connector, "get_tables", None)
        if get_tables is None:
            raise ToolError(self.spec.name, "this source does not expose schema introspection")
        tables = list(await maybe_await(get_tables()) or [])
        get_columns = getattr(connector, "get_columns", None)
        get_relationships = getattr(connector, "get_relationships", None)
        columns = {}
        for table in tables:
            name = table if isinstance(table, str) else str(table.get("name", table))
            columns[name] = list(await maybe_await(get_columns(name)) or []) if get_columns else []
        relationships = list(await maybe_await(get_relationships()) or []) if get_relationships else []
        return {"tables": tables, "columns": columns, "relationships": relationships}


class GetDatabaseRecordTool(Tool):
    spec = ToolSpec(
        name="get_database_record",
        description="Fetch one record by table and primary key, as citable evidence.",
        agent=AgentName.DATABASE,
        input_schema=obj(
            {
                "table": string("Table name"),
                "record_id": string("Primary key value"),
                "source_id": string("Source id of the database"),
            },
            required=["table", "record_id"],
        ),
        output_schema=RECORDS_OUTPUT,
        timeout_seconds=DB_TIMEOUT_SECONDS,
        requires_flag="database",
        cost_hint=0.3,
    )

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        connector = await connector_for(ctx, self.spec.name, args.get("source_id"))
        get_record = getattr(connector, "get_record", None)
        if get_record is None:
            raise ToolError(self.spec.name, "this source does not expose single-record access")
        row = await maybe_await(get_record(args["table"], args["record_id"]))
        if not row:
            return self.empty(f"no {args['table']} record with id {args['record_id']}")
        items = await evidence_from_records(
            [dict(row)],
            source_id=args.get("source_id") or "database",
            table=args["table"],
            primary_key=next((k for k in row if k.endswith("_id") or k == "id"), "id"),
            retrieved_by=self.spec.name,
            services=ctx.services.evidence,
        )
        payload = evidence_payload(items)
        payload["records"] = [dict(row)]
        return self.success(
            data=payload,
            summary=f"{args['table']} record {args['record_id']}",
            count=1,
            evidence_ids=[item.evidence_id for item in items],
        )


DATABASE_TOOLS: tuple[type[Tool], ...] = (QueryDatabaseTool, GetDatabaseSchemaTool, GetDatabaseRecordTool)
