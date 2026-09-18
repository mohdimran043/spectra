"""SQLAlchemy async implementation of the control-plane repository.

One implementation serves both deployment profiles: SQLite (aiosqlite) on a
laptop and PostgreSQL (psycopg) on a cluster.  Writes are dialect-aware upserts
rather than read-modify-write, so re-ingesting the same asset is idempotent and
two ingest workers cannot race each other into a duplicate-key failure.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

from spectra_config import Settings
from spectra_config.logging import get_logger
from spectra_schemas import (
    Asset,
    CanonicalEntity,
    Chunk,
    EntityLink,
    IndexVersion,
    IngestJob,
    SourceDescriptor,
)
from sqlalchemy import Select, delete, event, func, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from . import mappers
from .models import (
    AssetRow,
    Base,
    ChunkRow,
    EntityKeyRow,
    EntityLinkRow,
    EntityRow,
    IndexVersionRow,
    IngestJobRow,
    SourceRow,
)
from .repository import Repository

log = get_logger(__name__)

POSTGRES_DIALECT = "postgresql"
SQLITE_DIALECT = "sqlite"
DEFAULT_CHUNK_BATCH = 500
DEFAULT_LIST_LIMIT = 200
SQLITE_CONNECT_TIMEOUT = 30
STATS_TABLES: dict[str, type[Base]] = {
    "sources": SourceRow,
    "assets": AssetRow,
    "chunks": ChunkRow,
    "entities": EntityRow,
    "entity_links": EntityLinkRow,
    "ingest_jobs": IngestJobRow,
    "index_versions": IndexVersionRow,
}


class SqlRepository(Repository):
    """Control-plane CRUD over SQLite or PostgreSQL."""

    def __init__(self, settings: Settings, url: str | None = None) -> None:
        self._settings = settings
        self._url = url or settings.database_url
        self._dialect = make_url(self._url).get_backend_name()
        self.backend_name = self._dialect
        connect_args = {"timeout": SQLITE_CONNECT_TIMEOUT} if self._is_sqlite else {}
        self._engine = create_async_engine(self._url, pool_pre_ping=True, connect_args=connect_args)
        if self._is_sqlite:
            event.listen(self._engine.sync_engine, "connect", _apply_sqlite_pragmas)
        self._sessions = async_sessionmaker(self._engine, expire_on_commit=False)

    @property
    def _is_sqlite(self) -> bool:
        return self._dialect == SQLITE_DIALECT

    # -- lifecycle --------------------------------------------------------
    async def initialise(self) -> None:
        async with self._engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        log.info("repository.initialised", backend=self.backend_name, url=self.safe_url)

    async def health(self) -> dict[str, Any]:
        try:
            async with self._sessions() as session:
                await session.execute(select(func.count()).select_from(SourceRow))
        except SQLAlchemyError as exc:
            log.warning("repository.health_failed", backend=self.backend_name, error=str(exc))
            return {"backend": self.backend_name, "status": "error", "detail": str(exc)}
        return {"backend": self.backend_name, "status": "ok", "url": self.safe_url}

    async def close(self) -> None:
        await self._engine.dispose()

    @property
    def safe_url(self) -> str:
        """Connection string with the password redacted - safe for logs and /health."""
        return make_url(self._url).render_as_string(hide_password=True)

    # -- internals --------------------------------------------------------
    def _insert(self, table: type[Base]) -> Any:
        return postgres_insert(table) if self._dialect == POSTGRES_DIALECT else sqlite_insert(table)

    async def _upsert(
        self, session: AsyncSession, table: type[Base], rows: Sequence[dict[str, Any]], keys: Sequence[str]
    ) -> int:
        if not rows:
            return 0
        statement = self._insert(table).values(list(rows))
        updatable = {name: getattr(statement.excluded, name) for name in rows[0] if name not in keys}
        if updatable:
            statement = statement.on_conflict_do_update(index_elements=list(keys), set_=updatable)
        else:
            statement = statement.on_conflict_do_nothing(index_elements=list(keys))
        await session.execute(statement)
        return len(rows)

    async def _scalars(self, statement: Select) -> list[Any]:
        async with self._sessions() as session:
            return list((await session.execute(statement)).scalars().all())

    async def _first(self, statement: Select) -> Any | None:
        async with self._sessions() as session:
            return (await session.execute(statement)).scalars().first()

    async def _count(self, statement: Select) -> int:
        async with self._sessions() as session:
            return int((await session.execute(statement)).scalar_one())

    # -- sources ----------------------------------------------------------
    async def upsert_source(self, source: SourceDescriptor) -> SourceDescriptor:
        async with self._sessions() as session, session.begin():
            await self._upsert(session, SourceRow, [mappers.source_values(source)], ["source_id"])
        return source

    async def get_source(self, source_id: str) -> SourceDescriptor | None:
        row = await self._first(select(SourceRow).where(SourceRow.source_id == source_id))
        return mappers.source_model(row) if row is not None else None

    async def list_sources(self) -> list[SourceDescriptor]:
        rows = await self._scalars(select(SourceRow).order_by(SourceRow.name))
        return [mappers.source_model(row) for row in rows]

    async def delete_source(self, source_id: str) -> bool:
        async with self._sessions() as session, session.begin():
            result = await session.execute(delete(SourceRow).where(SourceRow.source_id == source_id))
        return bool(result.rowcount)

    # -- assets -----------------------------------------------------------
    async def upsert_asset(self, asset: Asset) -> Asset:
        async with self._sessions() as session, session.begin():
            await self._upsert(session, AssetRow, [mappers.asset_values(asset)], ["asset_id"])
        return asset

    async def get_asset(self, asset_id: str) -> Asset | None:
        row = await self._first(select(AssetRow).where(AssetRow.asset_id == asset_id))
        return mappers.asset_model(row) if row is not None else None

    async def list_assets(
        self, source_id: str | None = None, kind: str | None = None, limit: int = DEFAULT_LIST_LIMIT, offset: int = 0
    ) -> list[Asset]:
        statement = select(AssetRow)
        if source_id:
            statement = statement.where(AssetRow.source_id == source_id)
        if kind:
            statement = statement.where(AssetRow.kind == _enum_value(kind))
        statement = statement.order_by(AssetRow.created_at.desc(), AssetRow.asset_id).limit(limit).offset(offset)
        return [mappers.asset_model(row) for row in await self._scalars(statement)]

    async def count_assets(self, source_id: str | None = None) -> int:
        statement = select(func.count()).select_from(AssetRow)
        if source_id:
            statement = statement.where(AssetRow.source_id == source_id)
        return await self._count(statement)

    async def find_asset_by_hash(self, content_hash: str) -> Asset | None:
        row = await self._first(
            select(AssetRow).where(AssetRow.content_hash == content_hash).order_by(AssetRow.created_at)
        )
        return mappers.asset_model(row) if row is not None else None

    # -- chunks -----------------------------------------------------------
    async def upsert_chunks(self, chunks: Sequence[Chunk]) -> int:
        if not chunks:
            return 0
        values = [mappers.chunk_values(chunk) for chunk in chunks]
        async with self._sessions() as session, session.begin():
            written = await self._upsert(session, ChunkRow, values, ["chunk_id"])
        log.debug("repository.chunks_upserted", backend=self.backend_name, count=written)
        return written

    async def get_chunk(self, chunk_id: str) -> Chunk | None:
        row = await self._first(select(ChunkRow).where(ChunkRow.chunk_id == chunk_id))
        return mappers.chunk_model(row) if row is not None else None

    async def get_chunks(self, chunk_ids: Sequence[str]) -> list[Chunk]:
        if not chunk_ids:
            return []
        rows = await self._scalars(select(ChunkRow).where(ChunkRow.chunk_id.in_(list(chunk_ids))))
        by_id = {row.chunk_id: row for row in rows}
        return [mappers.chunk_model(by_id[cid]) for cid in chunk_ids if cid in by_id]

    async def list_chunks_by_asset(self, asset_id: str) -> list[Chunk]:
        statement = select(ChunkRow).where(ChunkRow.asset_id == asset_id).order_by(ChunkRow.ordinal)
        return [mappers.chunk_model(row) for row in await self._scalars(statement)]

    async def iter_chunks(self, batch_size: int = DEFAULT_CHUNK_BATCH) -> AsyncIterator[list[Chunk]]:
        """Stream every chunk in keyset-paginated batches (reindexing reads the whole corpus)."""
        if batch_size <= 0:
            raise ValueError(f"batch_size must be positive, got {batch_size}")
        cursor = ""
        while True:
            statement = (
                select(ChunkRow).where(ChunkRow.chunk_id > cursor).order_by(ChunkRow.chunk_id).limit(batch_size)
            )
            rows = await self._scalars(statement)
            if not rows:
                return
            cursor = rows[-1].chunk_id
            yield [mappers.chunk_model(row) for row in rows]

    async def count_chunks(self, modality: str | None = None) -> int:
        statement = select(func.count()).select_from(ChunkRow)
        if modality:
            statement = statement.where(ChunkRow.modality == _enum_value(modality))
        return await self._count(statement)

    async def delete_chunks_for_asset(self, asset_id: str) -> int:
        async with self._sessions() as session, session.begin():
            links = await session.execute(delete(EntityLinkRow).where(EntityLinkRow.asset_id == asset_id))
            result = await session.execute(delete(ChunkRow).where(ChunkRow.asset_id == asset_id))
        removed = int(result.rowcount or 0)
        log.info(
            "repository.chunks_deleted",
            backend=self.backend_name,
            asset_id=asset_id,
            chunks=removed,
            entity_links=int(links.rowcount or 0),
        )
        return removed

    # -- entities ---------------------------------------------------------
    async def upsert_entity(self, entity: CanonicalEntity) -> CanonicalEntity:
        values = mappers.entity_values(entity)
        keys = [{"normalized_key": key, "entity_id": entity.entity_id} for key in entity.normalized_keys]
        async with self._sessions() as session, session.begin():
            await self._upsert(session, EntityRow, [values], ["entity_id"])
            await session.execute(delete(EntityKeyRow).where(EntityKeyRow.entity_id == entity.entity_id))
            await self._upsert(session, EntityKeyRow, keys, ["normalized_key", "entity_id"])
        return entity

    async def get_entity(self, entity_id: str) -> CanonicalEntity | None:
        row = await self._first(select(EntityRow).where(EntityRow.entity_id == entity_id))
        return mappers.entity_model(row) if row is not None else None

    async def find_entities_by_key(self, normalized_key: str) -> list[CanonicalEntity]:
        statement = (
            select(EntityRow)
            .join(EntityKeyRow, EntityKeyRow.entity_id == EntityRow.entity_id)
            .where(EntityKeyRow.normalized_key == normalized_key)
            .order_by(EntityRow.canonical_name)
        )
        return [mappers.entity_model(row) for row in await self._scalars(statement)]

    async def list_entities(
        self, entity_type: str | None = None, limit: int = DEFAULT_LIST_LIMIT, offset: int = 0
    ) -> list[CanonicalEntity]:
        statement = select(EntityRow)
        if entity_type:
            statement = statement.where(EntityRow.entity_type == _enum_value(entity_type))
        statement = statement.order_by(EntityRow.canonical_name).limit(limit).offset(offset)
        return [mappers.entity_model(row) for row in await self._scalars(statement)]

    async def search_entities(self, text: str, limit: int = 20) -> list[CanonicalEntity]:
        needle = (text or "").strip()
        if not needle:
            return []
        pattern = f"%{needle}%"
        matched_ids = select(EntityKeyRow.entity_id).where(EntityKeyRow.normalized_key.ilike(pattern))
        statement = (
            select(EntityRow)
            .where(EntityRow.canonical_name.ilike(pattern) | EntityRow.entity_id.in_(matched_ids))
            .order_by(EntityRow.mention_count.desc(), EntityRow.canonical_name)
            .limit(limit)
        )
        return [mappers.entity_model(row) for row in await self._scalars(statement)]

    async def upsert_entity_links(self, links: Sequence[EntityLink]) -> int:
        if not links:
            return 0
        values = [mappers.link_values(link) for link in links]
        async with self._sessions() as session, session.begin():
            return await self._upsert(session, EntityLinkRow, values, ["entity_id", "chunk_id"])

    async def links_for_entity(self, entity_id: str, limit: int = DEFAULT_LIST_LIMIT) -> list[EntityLink]:
        statement = (
            select(EntityLinkRow)
            .where(EntityLinkRow.entity_id == entity_id)
            .order_by(EntityLinkRow.confidence.desc(), EntityLinkRow.chunk_id)
            .limit(limit)
        )
        return [mappers.link_model(row) for row in await self._scalars(statement)]

    async def links_for_chunk(self, chunk_id: str) -> list[EntityLink]:
        statement = (
            select(EntityLinkRow).where(EntityLinkRow.chunk_id == chunk_id).order_by(EntityLinkRow.entity_id)
        )
        return [mappers.link_model(row) for row in await self._scalars(statement)]

    # -- ingest jobs ------------------------------------------------------
    async def upsert_job(self, job: IngestJob) -> IngestJob:
        async with self._sessions() as session, session.begin():
            await self._upsert(session, IngestJobRow, [mappers.job_values(job)], ["job_id"])
        return job

    async def get_job(self, job_id: str) -> IngestJob | None:
        row = await self._first(select(IngestJobRow).where(IngestJobRow.job_id == job_id))
        return mappers.job_model(row) if row is not None else None

    async def list_jobs(self, limit: int = 50) -> list[IngestJob]:
        statement = select(IngestJobRow).order_by(IngestJobRow.updated_at.desc(), IngestJobRow.job_id).limit(limit)
        return [mappers.job_model(row) for row in await self._scalars(statement)]

    # -- index versioning -------------------------------------------------
    async def record_index_version(self, version: IndexVersion) -> None:
        async with self._sessions() as session, session.begin():
            await self._upsert(
                session, IndexVersionRow, [mappers.index_version_values(version)], ["index_version"]
            )

    async def active_index_version(self) -> IndexVersion | None:
        """The most recently recorded version - reindexing always writes a new row."""
        row = await self._first(
            select(IndexVersionRow).order_by(
                IndexVersionRow.created_at.desc(), IndexVersionRow.index_version.desc()
            )
        )
        return mappers.index_version_model(row) if row is not None else None

    async def list_index_versions(self) -> list[IndexVersion]:
        statement = select(IndexVersionRow).order_by(IndexVersionRow.created_at.desc())
        return [mappers.index_version_model(row) for row in await self._scalars(statement)]

    # -- audit ------------------------------------------------------------
    async def stats(self) -> dict[str, int]:
        totals: dict[str, int] = {}
        async with self._sessions() as session:
            for name, table in STATS_TABLES.items():
                result = await session.execute(select(func.count()).select_from(table))
                totals[name] = int(result.scalar_one())
        return totals


def _apply_sqlite_pragmas(connection: Any, _record: Any) -> None:
    """WAL keeps readers unblocked during ingestion; foreign keys are off by default.

    ``connection`` is the DBAPI connection - for aiosqlite that is SQLAlchemy's
    sync-adapter wrapper rather than a bare ``sqlite3.Connection``, so the
    pragmas are issued through the cursor API both objects share.
    """
    cursor = connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _jsonable(params: dict[str, Any]) -> dict[str, Any]:
    """Bound SQL parameters may hold dates or Decimals; keep the audit row JSON-safe."""
    safe: dict[str, Any] = {}
    for key, value in (params or {}).items():
        safe[str(key)] = value if isinstance(value, (str, int, float, bool)) or value is None else str(value)
    return safe
