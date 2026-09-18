"""Schema introspection shared by every SQL dialect.

The Database Agent needs tables, columns and foreign keys in one shape whether
the source is PostgreSQL, MySQL or SQLite.  SQLAlchemy's ``Inspector`` already
issues the right catalog query per dialect (``information_schema`` on
PostgreSQL/MySQL, ``PRAGMA table_info`` / ``PRAGMA foreign_key_list`` on
SQLite), so this module adapts its output to SPECTRA's immutable value objects
instead of re-implementing three catalog dialects.

All functions here are blocking; callers run them on a worker thread.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from spectra_config.logging import get_logger
from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from .errors import ConnectionFailed
from .sql_types import ColumnInfo, Relationship, TableInfo

log = get_logger(__name__)


def list_tables(engine: Engine, schema: str | None = None) -> tuple[str, ...]:
    """Every table and view name the connected role can see."""
    try:
        inspector = inspect(engine)
        names = list(inspector.get_table_names(schema=schema))
        names.extend(inspector.get_view_names(schema=schema))
    except SQLAlchemyError as exc:
        raise ConnectionFailed(f"cannot list tables: {exc}") from exc
    return tuple(sorted(dict.fromkeys(names)))


def describe_table(engine: Engine, table: str, schema: str | None = None) -> TableInfo:
    """Columns + primary key for one table."""
    try:
        inspector = inspect(engine)
        raw_columns = inspector.get_columns(table, schema=schema)
        primary_key = tuple(_primary_key(inspector, table, schema))
    except SQLAlchemyError as exc:
        raise ConnectionFailed(f"cannot describe table {table!r}: {exc}") from exc
    columns = tuple(_column_info(raw, primary_key) for raw in raw_columns)
    return TableInfo(name=table, columns=columns, primary_key=primary_key)


def list_relationships(
    engine: Engine,
    tables: Sequence[str],
    schema: str | None = None,
) -> tuple[Relationship, ...]:
    """Foreign keys for ``tables``, in a dialect-independent shape."""
    try:
        inspector = inspect(engine)
    except SQLAlchemyError as exc:
        raise ConnectionFailed(f"cannot inspect relationships: {exc}") from exc
    relationships: list[Relationship] = []
    for table in tables:
        try:
            raw_keys = inspector.get_foreign_keys(table, schema=schema)
        except SQLAlchemyError as exc:
            log.warning("sql.foreign_keys_unavailable", table=table, error=str(exc))
            continue
        relationships.extend(_relationship(table, raw) for raw in raw_keys if raw.get("referred_table"))
    return tuple(relationships)


def _primary_key(inspector: Any, table: str, schema: str | None) -> list[str]:
    constraint = inspector.get_pk_constraint(table, schema=schema) or {}
    return [str(name) for name in constraint.get("constrained_columns") or []]


def _column_info(raw: dict[str, Any], primary_key: Sequence[str]) -> ColumnInfo:
    name = str(raw.get("name"))
    default = raw.get("default")
    return ColumnInfo(
        name=name,
        data_type=str(raw.get("type")),
        nullable=bool(raw.get("nullable", True)),
        primary_key=name in primary_key,
        default=None if default is None else str(default),
    )


def _relationship(table: str, raw: dict[str, Any]) -> Relationship:
    return Relationship(
        table=table,
        columns=tuple(str(name) for name in raw.get("constrained_columns") or []),
        referred_table=str(raw.get("referred_table")),
        referred_columns=tuple(str(name) for name in raw.get("referred_columns") or []),
        constraint_name=None if raw.get("name") is None else str(raw.get("name")),
    )


def count_rows(engine: Engine, table: str, quoted: str) -> int:
    """Approximate-free row count used for health and catalog counters.

    ``quoted`` must already be a guard-validated, dialect-quoted identifier -
    counts cannot use bound parameters for the table name.
    """
    from sqlalchemy import text

    try:
        with engine.connect() as connection:
            value = connection.execute(text(f"SELECT COUNT(*) FROM {quoted}")).scalar()
            connection.rollback()
    except SQLAlchemyError as exc:
        log.warning("sql.count_failed", table=table, error=str(exc))
        return 0
    return int(value or 0)
