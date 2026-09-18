"""The single entry point every service uses to reach storage.

``get_storage()`` returns a lazily-constructed ``Storage`` bundle whose members
are chosen from configuration.  Callers never import a backend directly, so
swapping SQLite for Qdrant/OpenSearch/Neo4j is a `.env` change.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from spectra_config import Settings, get_settings
from spectra_config.logging import get_logger

from .interfaces import CacheStore, GraphStore, LexicalStore, ObjectStore, VectorStore

log = get_logger(__name__)

# Collection / index names.  Text and multimodal vectors live in separate
# collections because they have different dimensions and different models.
TEXT_COLLECTION = "spectra_text"
IMAGE_COLLECTION = "spectra_image"
LEXICAL_INDEX = "spectra_lexical"


@dataclass
class Storage:
    """Bundle of the six stores plus the relational repository."""

    vectors: VectorStore
    lexical: LexicalStore
    graph: GraphStore
    objects: ObjectStore
    cache: CacheStore
    repository: Any  # spectra_storage.repository.Repository
    settings: Settings

    async def health(self) -> dict[str, dict[str, Any]]:
        names = ("vectors", "lexical", "graph", "objects", "cache")
        stores = (self.vectors, self.lexical, self.graph, self.objects, self.cache)
        results = await asyncio.gather(*(s.health() for s in stores), return_exceptions=True)
        report: dict[str, dict[str, Any]] = {}
        for name, store, result in zip(names, stores, results, strict=True):
            if isinstance(result, BaseException):
                report[name] = {
                    "backend": getattr(store, "backend_name", "unknown"),
                    "status": "error",
                    "detail": str(result),
                }
            else:
                report[name] = result
        try:
            report["relational"] = await self.repository.health()
        except Exception as exc:  # pragma: no cover - defensive
            report["relational"] = {"status": "error", "detail": str(exc)}
        return report

    async def close(self) -> None:
        for store in (self.vectors, self.lexical, self.graph, self.objects, self.cache):
            try:
                await store.close()
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("storage.close_failed", store=type(store).__name__, error=str(exc))
        try:
            await self.repository.close()
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("storage.close_failed", store="repository", error=str(exc))


_storage: Storage | None = None
_lock = asyncio.Lock()


async def get_storage(settings: Settings | None = None) -> Storage:
    """Return the process-wide storage bundle, constructing it on first use."""
    global _storage
    if _storage is not None:
        return _storage
    async with _lock:
        if _storage is None:
            from .factory import build_storage

            _storage = await build_storage(settings or get_settings())
    return _storage


async def reset_storage() -> None:
    """Drop the cached bundle (used by tests and by re-configuration)."""
    global _storage
    async with _lock:
        if _storage is not None:
            await _storage.close()
        _storage = None
