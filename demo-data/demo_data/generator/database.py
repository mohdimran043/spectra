"""Emit the enterprise dataset as a real SQLite database and as PostgreSQL SQL.

Both emissions come from the same in-memory rows, so the ``enterprise`` schema
in PostgreSQL and the laptop SQLite file are guaranteed to agree.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from spectra_config.logging import get_logger

from .constants import SQL_FILENAME, SQLITE_FILENAME
from .records import AssetRecord, CustomerRecord, EnterpriseData, IncidentRecord, TransactionRecord
from .rng import iso

log = get_logger(__name__)

SCHEMA_NAME: Final[str] = "enterprise"
SCHEMA_FILENAME: Final[str] = "enterprise_schema.sql"
INSERT_BATCH: Final[int] = 1_000

CUSTOMER_COLUMNS: Final[tuple[str, ...]] = (
    "customer_id", "name", "email", "segment", "country", "risk_score", "created_at", "status",
)
TRANSACTION_COLUMNS: Final[tuple[str, ...]] = (
    "transaction_id", "customer_id", "amount", "currency", "status", "method", "failure_reason",
    "created_at", "updated_at", "incident_id",
)
INCIDENT_COLUMNS: Final[tuple[str, ...]] = (
    "incident_id", "title", "severity", "status", "category", "root_cause", "service",
    "opened_at", "resolved_at", "approved", "approved_by",
)
ASSET_COLUMNS: Final[tuple[str, ...]] = (
    "asset_id", "name", "kind", "owner", "environment", "service", "status", "created_at",
)

_TABLE_DDL: Final[tuple[tuple[str, str], ...]] = (
    (
        "customers",
        "customer_id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL, segment TEXT NOT NULL, "
        "country TEXT NOT NULL, risk_score REAL NOT NULL, created_at TIMESTAMP NOT NULL, status TEXT NOT NULL",
    ),
    (
        "transactions",
        "transaction_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, amount NUMERIC(14,2) NOT NULL, "
        "currency TEXT NOT NULL, status TEXT NOT NULL, method TEXT NOT NULL, failure_reason TEXT, "
        "created_at TIMESTAMP NOT NULL, updated_at TIMESTAMP NOT NULL, incident_id TEXT",
    ),
    (
        "incidents",
        "incident_id TEXT PRIMARY KEY, title TEXT NOT NULL, severity TEXT NOT NULL, status TEXT NOT NULL, "
        "category TEXT NOT NULL, root_cause TEXT NOT NULL, service TEXT NOT NULL, "
        "opened_at TIMESTAMP NOT NULL, resolved_at TIMESTAMP, approved BOOLEAN NOT NULL, approved_by TEXT",
    ),
    (
        "assets",
        "asset_id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, owner TEXT NOT NULL, "
        "environment TEXT NOT NULL, service TEXT NOT NULL, status TEXT NOT NULL, created_at TIMESTAMP NOT NULL",
    ),
)

_INDEX_DDL: Final[tuple[str, ...]] = (
    "CREATE INDEX IF NOT EXISTS idx_transactions_customer ON {p}transactions(customer_id)",
    "CREATE INDEX IF NOT EXISTS idx_transactions_status ON {p}transactions(status)",
    "CREATE INDEX IF NOT EXISTS idx_transactions_incident ON {p}transactions(incident_id)",
    "CREATE INDEX IF NOT EXISTS idx_incidents_service ON {p}incidents(service)",
    "CREATE INDEX IF NOT EXISTS idx_assets_service ON {p}assets(service)",
)


@dataclass(frozen=True)
class DatabaseArtifacts:
    sqlite_path: Path
    schema_sql_path: Path
    inserts_sql_path: Path
    counts: dict[str, int]


def _customer_row(record: CustomerRecord) -> tuple[Any, ...]:
    return (
        record.customer_id, record.name, record.email, record.segment, record.country,
        record.risk_score, iso(record.created_at), record.status,
    )


def _transaction_row(record: TransactionRecord) -> tuple[Any, ...]:
    return (
        record.transaction_id, record.customer_id, record.amount, record.currency, record.status,
        record.method, record.failure_reason, iso(record.created_at), iso(record.updated_at),
        record.incident_id,
    )


def _incident_row(record: IncidentRecord) -> tuple[Any, ...]:
    return (
        record.incident_id, record.title, record.severity, record.status, record.category,
        record.root_cause, record.service, iso(record.opened_at),
        iso(record.resolved_at) if record.resolved_at else None,
        1 if record.approved else 0, record.approved_by,
    )


def _asset_row(record: AssetRecord) -> tuple[Any, ...]:
    return (
        record.asset_id, record.name, record.kind, record.owner, record.environment,
        record.service, record.status, iso(record.created_at),
    )


def table_rows(data: EnterpriseData) -> dict[str, tuple[tuple[str, ...], list[tuple[Any, ...]]]]:
    """Columns plus rows for each table, in a stable, deterministic order."""
    return {
        "customers": (CUSTOMER_COLUMNS, [_customer_row(record) for record in data.customers]),
        "transactions": (TRANSACTION_COLUMNS, [_transaction_row(record) for record in data.transactions]),
        "incidents": (INCIDENT_COLUMNS, [_incident_row(record) for record in data.incidents]),
        "assets": (ASSET_COLUMNS, [_asset_row(record) for record in data.assets]),
    }


def _ddl_statements(prefix: str) -> Iterable[str]:
    for table, body in _TABLE_DDL:
        yield f"CREATE TABLE IF NOT EXISTS {prefix}{table} (\n    {body}\n);"
    for template in _INDEX_DDL:
        yield template.format(p=prefix) + ";"


def write_sqlite(path: Path, data: EnterpriseData) -> dict[str, int]:
    """Create (or replace) the embedded enterprise database."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    counts: dict[str, int] = {}
    connection = sqlite3.connect(path)
    try:
        for statement in _ddl_statements(""):
            connection.execute(statement)
        for table, (columns, rows) in table_rows(data).items():
            placeholders = ", ".join("?" for _ in columns)
            sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
            for start in range(0, len(rows), INSERT_BATCH):
                connection.executemany(sql, rows[start : start + INSERT_BATCH])
            counts[table] = len(rows)
        connection.commit()
    finally:
        connection.close()
    log.info("demo_data.sqlite_written", path=str(path), **counts)
    return counts


def _literal(value: Any, *, column: str) -> str:
    if value is None:
        return "NULL"
    if column == "approved":
        return "TRUE" if value else "FALSE"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def _insert_statements(table: str, columns: Sequence[str], rows: Sequence[tuple[Any, ...]]) -> Iterable[str]:
    column_list = ", ".join(columns)
    for start in range(0, len(rows), INSERT_BATCH):
        batch = rows[start : start + INSERT_BATCH]
        values = ",\n    ".join(
            "(" + ", ".join(_literal(value, column=columns[index]) for index, value in enumerate(row)) + ")"
            for row in batch
        )
        yield f"INSERT INTO {SCHEMA_NAME}.{table} ({column_list}) VALUES\n    {values}\nON CONFLICT DO NOTHING;"


def write_postgres_sql(directory: Path, data: EnterpriseData) -> tuple[Path, Path]:
    """Write the PostgreSQL DDL and the matching INSERT script."""
    directory.mkdir(parents=True, exist_ok=True)
    schema_path = directory / SCHEMA_FILENAME
    inserts_path = directory / SQL_FILENAME
    prefix = f"{SCHEMA_NAME}."
    header = (
        "-- SPECTRA enterprise demo schema.\n"
        "-- Generated by demo_data.generator - do not edit by hand.\n"
        f"CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME};\n"
    )
    schema_path.write_text(header + "\n".join(_ddl_statements(prefix)) + "\n", encoding="utf-8")

    parts = ["-- SPECTRA enterprise demo data.", "-- Generated by demo_data.generator.", "BEGIN;"]
    for table, (columns, rows) in table_rows(data).items():
        parts.extend(_insert_statements(table, columns, rows))
    parts.append("COMMIT;")
    inserts_path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    log.info("demo_data.sql_written", schema=str(schema_path), inserts=str(inserts_path))
    return schema_path, inserts_path


def emit_database(directory: Path, sqlite_path: Path, data: EnterpriseData) -> DatabaseArtifacts:
    counts = write_sqlite(sqlite_path, data)
    schema_path, inserts_path = write_postgres_sql(directory, data)
    return DatabaseArtifacts(
        sqlite_path=sqlite_path,
        schema_sql_path=schema_path,
        inserts_sql_path=inserts_path,
        counts=counts,
    )


def default_sqlite_path(repo_root: Path) -> Path:
    return repo_root / "data" / "runtime" / SQLITE_FILENAME
