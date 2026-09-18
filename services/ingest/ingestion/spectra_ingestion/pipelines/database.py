"""Database pipeline: connector rows -> readable text chunks -> indexes.

Rows arrive as an iterator supplied by a connector, are serialised in batches
and indexed batch by batch, so a million-row table never lands in memory.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from spectra_ai_core.gateway import ModelGateway
from spectra_config.logging import get_logger
from spectra_schemas import Asset, Chunk, DatabaseLocator, Modality

from ..entity_hook import EntityExtractor
from ..indexer import Indexer
from .base import STAGE_EXTRACT, BasePipeline, IngestResult, JobContext, build_chunk

log = get_logger(__name__)

ROW_BATCH: Final[int] = 200
MAX_VALUE_CHARS: Final[int] = 2000
ISO_FORMATS: Final[tuple[str, ...]] = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S")

Row = Mapping[str, Any]
RowSource = Iterable[Row] | AsyncIterator[Row]


@dataclass(frozen=True)
class TableSchema:
    """The minimum a connector must tell us about the rows it is streaming."""

    table: str
    primary_key: str
    columns: tuple[str, ...] = ()
    description: str = ""
    timestamp_column: str | None = None


class DatabasePipeline(BasePipeline):
    """Serialises structured rows into retrievable, fully-located chunks."""

    modality = Modality.DATABASE

    def __init__(
        self,
        indexer: Indexer,
        gateway: ModelGateway,
        *,
        entity_extractor: EntityExtractor | None = None,
        batch_size: int = ROW_BATCH,
    ) -> None:
        super().__init__(indexer, gateway, entity_extractor=entity_extractor)
        self._batch_size = batch_size

    async def run(self, asset: Asset, job_ctx: JobContext) -> IngestResult:
        schema = _require_schema(job_ctx)
        rows = job_ctx.payload.get("rows")
        if rows is None:
            raise ValueError(f"job {job_ctx.job_id}: database ingestion requires 'rows' in the payload")

        indexed_asset = asset.model_copy(
            update={
                "metadata": {
                    **asset.metadata,
                    "table": schema.table,
                    "primary_key": schema.primary_key,
                    "columns": list(schema.columns),
                    "description": schema.description,
                },
            }
        )
        return await self._stream(indexed_asset, schema, rows, job_ctx)

    async def _stream(
        self, asset: Asset, schema: TableSchema, rows: RowSource, job_ctx: JobContext
    ) -> IngestResult:
        warnings: list[str] = []
        totals = {"chunks": 0, "rows": 0, "batches": 0}
        first_batch = True
        batch: list[Chunk] = []

        async for row in _aiter_rows(rows):
            chunk = self._row_chunk(asset, schema, row, totals["rows"], warnings)
            totals["rows"] += 1
            if chunk is not None:
                batch.append(chunk)
            if len(batch) < self._batch_size:
                continue
            await self._flush(asset, batch, job_ctx, replace=first_batch, totals=totals, warnings=warnings)
            batch, first_batch = [], False

        if batch or first_batch:
            await self._flush(asset, batch, job_ctx, replace=first_batch, totals=totals, warnings=warnings)

        return IngestResult(
            asset=asset,
            chunk_count=totals["chunks"],
            warnings=tuple(warnings),
            metrics={"rows": totals["rows"], "batches": totals["batches"], "table": schema.table},
        )

    async def _flush(
        self,
        asset: Asset,
        batch: Sequence[Chunk],
        job_ctx: JobContext,
        *,
        replace: bool,
        totals: dict[str, int],
        warnings: list[str],
    ) -> None:
        result = await self.finalise(asset, batch, job_ctx, replace=replace)
        totals["chunks"] += result.chunk_count
        totals["batches"] += 1
        warnings.extend(result.warnings)
        await self.report(
            job_ctx, STAGE_EXTRACT, 0.6, f"indexed {totals['chunks']} rows from {asset.title}"
        )

    def _row_chunk(
        self, asset: Asset, schema: TableSchema, row: Row, ordinal: int, warnings: list[str]
    ) -> Chunk | None:
        try:
            record_id = _record_id(row, schema, ordinal)
            text = _row_text(schema, row, record_id)
        except Exception as exc:
            warnings.append(f"row_serialisation_failed [{ordinal}]: {exc}")
            log.warning("database.row_failed", ordinal=ordinal, error=str(exc))
            return None
        if not text:
            return None
        locator = DatabaseLocator(
            source_id=asset.source_id,
            table=schema.table,
            primary_key=schema.primary_key,
            record_id=record_id,
        )
        return build_chunk(
            asset,
            ordinal=ordinal,
            text=text,
            modality=Modality.DATABASE,
            locator=locator,
            title=f"{schema.table} {record_id}",
            metadata={"table": schema.table, "record_id": record_id},
            occurred_at=_occurred_at(row, schema),
            discriminator=f"row:{record_id}",
        )


def _require_schema(job_ctx: JobContext) -> TableSchema:
    schema = job_ctx.payload.get("schema")
    if not isinstance(schema, TableSchema):
        raise ValueError(f"job {job_ctx.job_id}: database ingestion requires a TableSchema payload")
    if not schema.table or not schema.primary_key:
        raise ValueError(f"job {job_ctx.job_id}: table and primary_key are required")
    return schema


async def _aiter_rows(rows: RowSource) -> AsyncIterator[Row]:
    """Accept either a plain iterable or an async iterator of rows."""
    if hasattr(rows, "__aiter__"):
        async for row in rows:  # type: ignore[union-attr]
            yield row
        return
    if not isinstance(rows, Iterable):
        raise TypeError("rows must be iterable or async-iterable")
    for row in rows:
        yield row


def _record_id(row: Row, schema: TableSchema, ordinal: int) -> str:
    value = row.get(schema.primary_key)
    return str(value) if value not in (None, "") else f"row_{ordinal}"


def _row_text(schema: TableSchema, row: Row, record_id: str) -> str:
    header = f"{schema.table} record where {schema.primary_key} is {record_id}."
    lines = [header]
    if schema.description:
        lines.append(schema.description)
    columns = schema.columns or tuple(row.keys())
    for column in columns:
        if column not in row:
            continue
        value = _format_value(row[column])
        if value:
            lines.append(f"{column}: {value}")
    return "\n".join(lines) if len(lines) > 1 else ""


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    text = " ".join(str(value).split())
    return text[:MAX_VALUE_CHARS]


def _occurred_at(row: Row, schema: TableSchema) -> datetime | None:
    if not schema.timestamp_column:
        return None
    raw = row.get(schema.timestamp_column)
    if isinstance(raw, datetime):
        return raw
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    for pattern in ISO_FORMATS:
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    return None


def iter_batches(rows: Iterable[Row], size: int = ROW_BATCH) -> Iterator[list[Row]]:
    """Batch helper for connectors that prefer to push rather than be pulled."""
    batch: list[Row] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
