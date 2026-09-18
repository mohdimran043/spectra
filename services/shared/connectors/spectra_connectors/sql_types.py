"""Immutable value objects exchanged by the SQL layer.

These are plain dataclasses rather than Pydantic models because they are
internal to the connector/agent boundary; whatever crosses the API is built
from them by the API layer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from spectra_schemas.provenance import DatabaseLocator


@dataclass(frozen=True, slots=True)
class ColumnInfo:
    """One column of a table as reported by the database's own catalog."""

    name: str
    data_type: str
    nullable: bool = True
    primary_key: bool = False
    default: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "data_type": self.data_type,
            "nullable": self.nullable,
            "primary_key": self.primary_key,
            "default": self.default,
        }


@dataclass(frozen=True, slots=True)
class Relationship:
    """A foreign key: ``table.columns -> referred_table.referred_columns``."""

    table: str
    columns: tuple[str, ...]
    referred_table: str
    referred_columns: tuple[str, ...]
    constraint_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "columns": list(self.columns),
            "referred_table": self.referred_table,
            "referred_columns": list(self.referred_columns),
            "constraint_name": self.constraint_name,
        }

    def human(self) -> str:
        left = ", ".join(self.columns)
        right = ", ".join(self.referred_columns)
        return f"{self.table}({left}) -> {self.referred_table}({right})"


@dataclass(frozen=True, slots=True)
class TableInfo:
    """A table plus its columns and primary key."""

    name: str
    columns: tuple[ColumnInfo, ...]
    primary_key: tuple[str, ...] = ()
    comment: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "columns": [column.to_dict() for column in self.columns],
            "primary_key": list(self.primary_key),
            "comment": self.comment,
        }


@dataclass(frozen=True, slots=True)
class QueryResult:
    """The outcome of one guarded read-only query."""

    columns: tuple[str, ...]
    rows: tuple[Mapping[str, Any], ...]
    sql: str
    elapsed_ms: float = 0.0
    truncated: bool = False
    row_limit: int = 0

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": list(self.columns),
            "rows": [dict(row) for row in self.rows],
            "row_count": self.row_count,
            "truncated": self.truncated,
            "row_limit": self.row_limit,
            "elapsed_ms": self.elapsed_ms,
            "sql": self.sql,
        }


@dataclass(frozen=True, slots=True)
class EntityHit:
    """One database row that matched an entity lookup, with its locator."""

    source_id: str
    entity_type: str
    table: str
    column: str
    value: str
    record: Mapping[str, Any] = field(default_factory=dict)
    locator: DatabaseLocator | None = None
    label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "entity_type": self.entity_type,
            "table": self.table,
            "column": self.column,
            "value": self.value,
            "label": self.label,
            "record": dict(self.record),
            "locator": None if self.locator is None else self.locator.model_dump(mode="json"),
        }


@dataclass(frozen=True, slots=True)
class ReadOnlyProbe:
    """Result of :meth:`SqlConnector.verify_read_only`.

    ``enforced`` is True only when the database itself refused a write - that is
    the difference between "we promise not to write" and "the role cannot write".
    """

    source_id: str
    enforced: bool
    detail: str
    probe: str
    checked_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "enforced": self.enforced,
            "detail": self.detail,
            "probe": self.probe,
            "checked_at": self.checked_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class EntityMapping:
    """Where an entity type lives in this database."""

    entity_type: str
    table: str
    column: str
    label_column: str | None = None
    primary_key: str | None = None

    @classmethod
    def from_payload(cls, entity_type: str, payload: Mapping[str, Any]) -> EntityMapping:
        table = str(payload.get("table") or "").strip()
        column = str(payload.get("column") or "").strip()
        if not table or not column:
            raise ValueError(f"entity mapping for {entity_type!r} needs both 'table' and 'column'")
        label = payload.get("label_column")
        primary_key = payload.get("primary_key")
        return cls(
            entity_type=entity_type,
            table=table,
            column=column,
            label_column=None if label is None else str(label),
            primary_key=None if primary_key is None else str(primary_key),
        )


def parse_entity_map(raw: Mapping[str, Any] | None) -> tuple[EntityMapping, ...]:
    """Parse ``connection['entity_map']`` into immutable mappings.

    Accepted shapes::

        {"customer": {"table": "customers", "column": "customer_id"}}
        {"customer": [{"table": "customers", "column": "customer_id"}, ...]}
    """
    if not raw:
        return ()
    mappings: list[EntityMapping] = []
    for entity_type, payload in raw.items():
        entries: Sequence[Any] = payload if isinstance(payload, (list, tuple)) else [payload]
        for entry in entries:
            if isinstance(entry, Mapping):
                mappings.append(EntityMapping.from_payload(str(entity_type), entry))
    return tuple(mappings)


@dataclass(frozen=True, slots=True)
class ValidatedSql:
    """A statement that passed every :class:`SqlGuard` check, with bound params.

    Nothing in the SQL layer executes a bare string: a
    :class:`~spectra_connectors.sql_session.ReadOnlySession` only accepts this
    type, so "validated" is enforced by the type system rather than by review.
    """

    sql: str
    params: Mapping[str, Any] = field(default_factory=dict)
    tables: frozenset[str] = frozenset()
    limit: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "sql": self.sql,
            "params": dict(self.params),
            "tables": sorted(self.tables),
            "limit": self.limit,
        }


@dataclass(frozen=True, slots=True)
class DatabaseRecord:
    """One row plus the locator that lets an analyst re-open it."""

    source_id: str
    table: str
    primary_key: str
    record_id: str
    record: Mapping[str, Any]
    locator: DatabaseLocator

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "table": self.table,
            "primary_key": self.primary_key,
            "record_id": self.record_id,
            "record": dict(self.record),
            "locator": self.locator.model_dump(mode="json"),
        }
