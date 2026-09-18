"""Read-only database querying with full SQL transparency."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from spectra_connectors.errors import (
    PermissionDenied,
    QueryFailed,
    QueryTimeout,
    SqlGuardError,
)

from ..dependencies import Container, Ctx, CtxManageSources, CtxRunSql, service_or_503
from ..errors import NotFound, SqlRejected, ValidationRejected
from ..errors import PermissionDenied as ApiPermissionDenied

router = APIRouter(tags=["database"])


# Column names whose values are canonical enterprise identifiers.  A row that
# came back from the database is itself proof the record exists, which is what
# lets us emit a *verified* application link without a second round trip.
ID_COLUMN_TO_TYPE: dict[str, str] = {
    "customer_id": "customer",
    "transaction_id": "transaction",
    "incident_id": "incident",
    "asset_id": "asset",
}


def _application_links(container: Container, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build deep links from ids actually present in the result set."""
    if container.evidence is None or not rows:
        return []

    from spectra_schemas import CanonicalEntity, EntityType, entity_id

    seen: dict[tuple[str, str], CanonicalEntity] = {}
    for row in rows:
        for column, type_name in ID_COLUMN_TO_TYPE.items():
            value = row.get(column)
            if not value or (type_name, str(value)) in seen:
                continue
            record_id = str(value)
            container.verified_records[f"{type_name}:{record_id}"] = True
            seen[(type_name, record_id)] = CanonicalEntity(
                entity_id=entity_id(type_name, record_id),
                entity_type=EntityType(type_name),
                canonical_name=record_id,
                attributes={"record_id": record_id},
            )

    return [link.model_dump() for link in container.evidence.application_links(list(seen.values()))]



class DatabaseQueryRequest(BaseModel):
    source_id: str
    question: str = ""
    sql: str | None = Field(default=None, description="Explicit SELECT; validated before execution")
    params: dict[str, Any] = Field(default_factory=dict)
    table: str | None = None
    limit: int | None = None


class DatabaseQueryResponse(BaseModel):
    sql: str
    params: dict[str, Any]
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool = False
    latency_ms: float = 0.0
    application_links: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/database/query", response_model=DatabaseQueryResponse)
async def query_database(
    body: DatabaseQueryRequest,
    container: Container,
    ctx: CtxRunSql,
) -> DatabaseQueryResponse:
    sources = service_or_503(container, "sources")
    connector = await sources.connector(body.source_id, ctx)
    if connector is None:
        raise NotFound(f"unknown source: {body.source_id!r}")

    if not body.sql:
        raise ValidationRejected(
            "supply `sql`; natural-language questions are answered through "
            "POST /api/investigations, which plans the query through the Database Agent"
        )
    try:
        result = await connector.query_readonly(body.sql, body.params or None, ctx)
    except SqlGuardError as exc:
        # A refused statement is a client error, not a server fault, and the
        # caller is entitled to know exactly which rule rejected it.
        raise SqlRejected(str(exc))
    except PermissionDenied as exc:
        raise ApiPermissionDenied(str(exc))
    except QueryTimeout as exc:
        raise SqlRejected(f"query exceeded the statement timeout: {exc}")
    except (QueryFailed, ValueError) as exc:
        raise SqlRejected(str(exc))

    links = _application_links(container, result.rows)

    return DatabaseQueryResponse(
        sql=result.sql,
        params=dict(body.params or {}),
        columns=list(result.columns),
        rows=[dict(row) for row in result.rows],
        row_count=len(result.rows),
        truncated=result.truncated,
        latency_ms=result.elapsed_ms,
        application_links=links,
    )


@router.get("/database/{source_id}/schema")
async def database_schema(source_id: str, container: Container, ctx: Ctx) -> dict[str, Any]:
    sources = service_or_503(container, "sources")
    connector = await sources.connector(source_id, ctx)
    if connector is None:
        raise NotFound(f"unknown source: {source_id!r}")
    return await connector.get_schema()


@router.get("/database/{source_id}/record/{table}/{record_id}")
async def database_record(
    source_id: str, table: str, record_id: str, container: Container, ctx: Ctx
) -> dict[str, Any]:
    sources = service_or_503(container, "sources")
    connector = await sources.connector(source_id, ctx)
    if connector is None:
        raise NotFound(f"unknown source: {source_id!r}")
    schema = await connector.get_schema()
    table_info = (schema.get("tables") or {}).get(table)
    if table_info is None:
        raise NotFound(f"unknown table: {table!r}")
    primary_key = next(
        (c["name"] for c in table_info["columns"] if c.get("primary_key")),
        f"{table.rstrip('s')}_id",
    )
    record = await connector.get_record(table, primary_key, record_id, ctx)
    if record is None:
        raise NotFound(f"no {table} record with id {record_id!r}")
    return record.to_dict() if hasattr(record, "to_dict") else dict(record)


@router.get("/database/audit")
async def sql_audit(container: Container, ctx: CtxManageSources) -> list[dict]:
    return await container.storage.repository.list_sql_audit(limit=200)
