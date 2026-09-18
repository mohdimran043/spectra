"""Qdrant-backed vector store (distributed profile).

Qdrant point ids must be unsigned integers or UUIDs, but SPECTRA addresses
everything by content-derived string ids such as ``chk_9f2...``.  Every id is
therefore mapped to a deterministic UUID5 and the original is carried in a
reserved payload key, so the same id that went in comes back out and the
embedded and distributed backends stay behaviourally identical.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from spectra_config import Settings
from spectra_config.logging import get_logger

from ..filters import OP_EQ, FilterCondition, compile_filters
from ..interfaces import VectorMatch, VectorRecord, VectorStore

log = get_logger(__name__)

ID_NAMESPACE = uuid.UUID("6f6d0f5a-9a0f-5f5e-9a3e-5d3c2b1a0e9d")
RESERVED_ID_KEY = "__spectra_id__"
DEFAULT_SEARCH_LIMIT = 50
CLIENT_TIMEOUT_SECONDS = 10


class QdrantVectorStore(VectorStore):
    """Dense retrieval against a Qdrant cluster."""

    backend_name = "qdrant"

    def __init__(self, settings: Settings) -> None:
        from qdrant_client import AsyncQdrantClient  # lazy: optional dependency

        self._settings = settings
        self._client = AsyncQdrantClient(url=settings.qdrant_url, timeout=CLIENT_TIMEOUT_SECONDS)

    # -- lifecycle --------------------------------------------------------
    async def probe(self) -> None:
        """Raise unless the cluster answers - used by the factory at start-up."""
        await self._client.get_collections()

    async def ensure_collection(self, name: str, dimension: int) -> None:
        from qdrant_client.models import Distance, VectorParams  # lazy

        if dimension <= 0:
            raise ValueError(f"collection {name!r} needs a positive dimension, got {dimension}")
        if await self._client.collection_exists(name):
            return
        await self._client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
        )
        log.info("vector.collection_created", backend=self.backend_name, collection=name, dimension=dimension)

    async def close(self) -> None:
        await self._client.close()

    # -- writes -----------------------------------------------------------
    async def upsert(self, collection: str, records: Sequence[VectorRecord]) -> int:
        from qdrant_client.models import PointStruct  # lazy

        if not records:
            return 0
        points = [
            PointStruct(
                id=_point_id(record.id),
                vector=[float(v) for v in record.vector],
                payload={**(record.payload or {}), RESERVED_ID_KEY: record.id},
            )
            for record in records
        ]
        await self._client.upsert(collection_name=collection, points=points, wait=True)
        log.debug("vector.upsert", backend=self.backend_name, collection=collection, count=len(points))
        return len(points)

    async def delete(self, collection: str, ids: Sequence[str]) -> int:
        from qdrant_client.models import PointIdsList  # lazy

        if not ids:
            return 0
        await self._client.delete(
            collection_name=collection,
            points_selector=PointIdsList(points=[_point_id(i) for i in ids]),
            wait=True,
        )
        return len(ids)

    # -- reads ------------------------------------------------------------
    async def search(
        self,
        collection: str,
        vector: Sequence[float],
        limit: int = DEFAULT_SEARCH_LIMIT,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorMatch]:
        query_filter = build_qdrant_filter(compile_filters(filters))
        query = [float(v) for v in vector]
        response = await self._client.query_points(
            collection_name=collection,
            query=query,
            limit=max(limit, 0),
            query_filter=query_filter,
            with_payload=True,
        )
        return [_to_match(point) for point in getattr(response, "points", response)]

    async def count(self, collection: str) -> int:
        result = await self._client.count(collection_name=collection, exact=True)
        return int(getattr(result, "count", 0))

    async def health(self) -> dict[str, Any]:
        try:
            collections = await self._client.get_collections()
        except Exception as exc:  # noqa: BLE001 - health must never raise
            log.warning("vector.health_failed", backend=self.backend_name, error=str(exc))
            return {"backend": self.backend_name, "status": "error", "detail": str(exc)}
        names = [c.name for c in getattr(collections, "collections", [])]
        return {
            "backend": self.backend_name,
            "status": "ok",
            "url": self._settings.qdrant_url,
            "collections": names,
        }


def build_qdrant_filter(conditions: Sequence[FilterCondition]) -> Any:
    """Translate compiled SPECTRA conditions into a Qdrant ``Filter``."""
    from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue  # lazy

    if not conditions:
        return None
    must = [
        FieldCondition(
            key=condition.field,
            match=(
                MatchValue(value=condition.single)
                if condition.operator == OP_EQ
                else MatchAny(any=list(condition.values))
            ),
        )
        for condition in conditions
    ]
    return Filter(must=must)


def _point_id(record_id: str) -> str:
    return str(uuid.uuid5(ID_NAMESPACE, record_id))


def _to_match(point: Any) -> VectorMatch:
    payload = dict(getattr(point, "payload", None) or {})
    record_id = str(payload.pop(RESERVED_ID_KEY, getattr(point, "id", "")))
    return VectorMatch(id=record_id, score=round(float(getattr(point, "score", 0.0)), 6), payload=payload)
