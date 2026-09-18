"""Embedded vector store: NumPy brute-force ANN over vectors kept in SQLite.

A laptop install must retrieve across hundreds of thousands of chunks without
Qdrant running.  Vectors are L2-normalised on write, so cosine similarity is a
single ``matrix @ query`` product; the matrix is cached in memory and rebuilt
lazily whenever a write invalidates it.  That keeps recall exact (no ANN
approximation error) while staying fast enough for the demonstration corpus.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from spectra_config import Settings
from spectra_config.logging import get_logger

from ..filters import FilterCondition, compile_filters, matches_payload
from ..interfaces import VectorMatch, VectorRecord, VectorStore
from ..sqlite_support import SqliteDatabase, fetch_all, safe_identifier, scalar

log = get_logger(__name__)

VECTOR_DB_FILENAME = "vectors.db"
TABLE_PREFIX = "vec_"
VECTOR_DTYPE = np.float32
MIN_NORM = 1e-12
DEFAULT_SEARCH_LIMIT = 50


@dataclass(frozen=True)
class _CollectionIndex:
    """Immutable in-memory snapshot of one collection."""

    ids: tuple[str, ...]
    payloads: tuple[dict[str, Any], ...]
    matrix: np.ndarray

    @property
    def size(self) -> int:
        return len(self.ids)


class EmbeddedVectorStore(VectorStore):
    """Pure-Python/NumPy vector search with SQLite persistence."""

    backend_name = "embedded"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._db = SqliteDatabase(settings.runtime_dir / VECTOR_DB_FILENAME)
        self._dimensions: dict[str, int] = {}
        self._cache: dict[str, _CollectionIndex] = {}

    # -- lifecycle --------------------------------------------------------
    async def ensure_collection(self, name: str, dimension: int) -> None:
        table = _table_for(name)
        if dimension <= 0:
            raise ValueError(f"collection {name!r} needs a positive dimension, got {dimension}")

        def _create(connection: sqlite3.Connection) -> int:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS vector_collections "
                "(name TEXT PRIMARY KEY, dimension INTEGER NOT NULL)"
            )
            connection.execute(
                f"CREATE TABLE IF NOT EXISTS {table} "
                "(id TEXT PRIMARY KEY, vector BLOB NOT NULL, payload TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO vector_collections(name, dimension) VALUES(?, ?) "
                "ON CONFLICT(name) DO NOTHING",
                (name, dimension),
            )
            return scalar(connection, "SELECT dimension FROM vector_collections WHERE name = ?", (name,))

        stored = await self._db.run(_create)
        if stored != dimension:
            raise ValueError(
                f"collection {name!r} already exists with dimension {stored}, refusing {dimension}"
            )
        self._dimensions[name] = dimension
        log.debug("vector.collection_ready", backend=self.backend_name, collection=name, dimension=dimension)

    async def close(self) -> None:
        self._cache = {}
        await self._db.close()

    # -- writes -----------------------------------------------------------
    async def upsert(self, collection: str, records: Sequence[VectorRecord]) -> int:
        table = _table_for(collection)
        if not records:
            return 0
        rows = [self._encode(collection, record) for record in records]

        def _write(connection: sqlite3.Connection) -> int:
            connection.executemany(
                f"INSERT INTO {table}(id, vector, payload) VALUES(?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET vector = excluded.vector, payload = excluded.payload",
                rows,
            )
            return len(rows)

        written = await self._db.run(_write)
        self._invalidate(collection)
        log.debug("vector.upsert", backend=self.backend_name, collection=collection, count=written)
        return written

    def _encode(self, collection: str, record: VectorRecord) -> tuple[str, bytes, str]:
        vector = np.asarray(record.vector, dtype=VECTOR_DTYPE)
        if vector.ndim != 1 or vector.size == 0:
            raise ValueError(f"record {record.id!r} must carry a non-empty 1-D vector")
        expected = self._dimensions.get(collection)
        if expected is not None and vector.size != expected:
            raise ValueError(
                f"record {record.id!r} has dimension {vector.size}, collection {collection!r} expects {expected}"
            )
        return (record.id, _normalise(vector, record.id).tobytes(), json.dumps(record.payload or {}))

    async def delete(self, collection: str, ids: Sequence[str]) -> int:
        table = _table_for(collection)
        if not ids:
            return 0

        def _delete(connection: sqlite3.Connection) -> int:
            cursor = connection.executemany(f"DELETE FROM {table} WHERE id = ?", [(i,) for i in ids])
            return int(cursor.rowcount or 0)

        removed = await self._db.run(_delete)
        self._invalidate(collection)
        return removed

    def _invalidate(self, collection: str) -> None:
        self._cache = {k: v for k, v in self._cache.items() if k != collection}

    # -- reads ------------------------------------------------------------
    async def search(
        self,
        collection: str,
        vector: Sequence[float],
        limit: int = DEFAULT_SEARCH_LIMIT,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorMatch]:
        conditions = compile_filters(filters)
        index = await self._index(collection)
        if index.size == 0 or limit <= 0:
            return []
        query = _normalise(np.asarray(vector, dtype=VECTOR_DTYPE), "query")
        if query.size != index.matrix.shape[1]:
            raise ValueError(
                f"query dimension {query.size} does not match collection {collection!r} "
                f"dimension {index.matrix.shape[1]}"
            )
        return await asyncio.to_thread(_rank, index, query, conditions, limit)

    async def count(self, collection: str) -> int:
        table = _table_for(collection)

        def _count(connection: sqlite3.Connection) -> int:
            # A collection that has never been written to holds nothing; that is
            # an empty index, not an error (health and search both call this).
            row = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
            ).fetchone()
            if row is None:
                return 0
            return scalar(connection, f"SELECT COUNT(*) FROM {table}")

        return await self._db.run(_count)

    async def health(self) -> dict[str, Any]:
        def _collections(connection: sqlite3.Connection) -> list[sqlite3.Row]:
            # The registry table only exists once a collection has been created;
            # an empty index is healthy, not broken.
            connection.execute(
                "CREATE TABLE IF NOT EXISTS vector_collections "
                "(name TEXT PRIMARY KEY, dimension INTEGER NOT NULL)"
            )
            return fetch_all(connection, "SELECT name, dimension FROM vector_collections ORDER BY name")

        try:
            rows = await self._db.run(_collections)
        except sqlite3.Error as exc:
            log.warning("vector.health_failed", backend=self.backend_name, error=str(exc))
            return {"backend": self.backend_name, "status": "error", "detail": str(exc)}
        return {
            "backend": self.backend_name,
            "status": "ok",
            "path": str(self._db.path),
            "collections": {row["name"]: row["dimension"] for row in rows},
        }

    async def _index(self, collection: str) -> _CollectionIndex:
        cached = self._cache.get(collection)
        if cached is not None:
            return cached
        table = _table_for(collection)

        def _load(connection: sqlite3.Connection) -> list[sqlite3.Row]:
            return fetch_all(connection, f"SELECT id, vector, payload FROM {table} ORDER BY id")

        rows = await self._db.run(_load)
        index = _build_index(rows)
        self._cache = {**self._cache, collection: index}
        log.debug("vector.index_built", backend=self.backend_name, collection=collection, size=index.size)
        return index


def _table_for(collection: str) -> str:
    return f"{TABLE_PREFIX}{safe_identifier(collection)}"


def _normalise(vector: np.ndarray, label: str) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm < MIN_NORM:
        log.warning("vector.zero_norm", label=label)
        return vector.astype(VECTOR_DTYPE, copy=True)
    return (vector / norm).astype(VECTOR_DTYPE, copy=False)


def _build_index(rows: Sequence[sqlite3.Row]) -> _CollectionIndex:
    if not rows:
        return _CollectionIndex(ids=(), payloads=(), matrix=np.zeros((0, 0), dtype=VECTOR_DTYPE))
    vectors = [np.frombuffer(row["vector"], dtype=VECTOR_DTYPE) for row in rows]
    width = vectors[0].size
    mismatched = [row["id"] for row, vec in zip(rows, vectors, strict=True) if vec.size != width]
    if mismatched:
        raise ValueError(f"stored vectors have inconsistent dimensions, offending ids: {mismatched[:5]}")
    return _CollectionIndex(
        ids=tuple(row["id"] for row in rows),
        payloads=tuple(json.loads(row["payload"]) for row in rows),
        matrix=np.vstack(vectors).astype(VECTOR_DTYPE, copy=False),
    )


def _rank(
    index: _CollectionIndex,
    query: np.ndarray,
    conditions: Sequence[FilterCondition],
    limit: int,
) -> list[VectorMatch]:
    positions = _eligible(index, conditions)
    if positions.size == 0:
        return []
    scores = index.matrix[positions] @ query
    take = min(limit, scores.size)
    top = np.argpartition(-scores, take - 1)[:take] if take < scores.size else np.arange(scores.size)
    ordered = top[np.argsort(-scores[top], kind="stable")]
    return [
        VectorMatch(
            id=index.ids[positions[i]],
            score=round(float(scores[i]), 6),
            payload=dict(index.payloads[positions[i]]),
        )
        for i in ordered
    ]


def _eligible(index: _CollectionIndex, conditions: Sequence[FilterCondition]) -> np.ndarray:
    if not conditions:
        return np.arange(index.size)
    keep = [i for i, payload in enumerate(index.payloads) if matches_payload(payload, conditions)]
    return np.asarray(keep, dtype=np.int64)
