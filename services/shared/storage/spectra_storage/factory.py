"""Backend selection with automatic degradation to the embedded profile.

SPECTRA must start even when half the infrastructure is down: an analyst opening
the UI while Qdrant is being restarted should get a *degraded* system that still
answers, not a stack trace.  Every distributed backend is therefore probed at
construction time and, on failure, replaced by its embedded counterpart with the
reason recorded in a structured log line and surfaced through ``/health``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, TypeVar

from spectra_config import (
    CacheBackend,
    GraphBackend,
    LexicalBackend,
    ObjectBackend,
    RelationalBackend,
    Settings,
    VectorBackend,
)
from spectra_config.logging import get_logger

from .backends.cache_memory import MemoryCacheStore
from .backends.graph_embedded import EmbeddedGraphStore
from .backends.lexical_embedded import EmbeddedLexicalStore
from .backends.object_filesystem import FilesystemObjectStore
from .backends.vector_embedded import EmbeddedVectorStore
from .facade import LEXICAL_INDEX, Storage
from .interfaces import CacheStore, GraphStore, LexicalStore, ObjectStore, VectorStore
from .repository import Repository
from .repository_sql import SqlRepository

log = get_logger(__name__)

PROBE_TIMEOUT_SECONDS = 5.0
REPOSITORY_TIMEOUT_SECONDS = 15.0

T = TypeVar("T")


async def build_storage(settings: Settings) -> Storage:
    """Construct the storage bundle described by ``settings``.

    Awaited by ``facade.get_storage``; distributed backends that fail to answer
    within ``PROBE_TIMEOUT_SECONDS`` are swapped for their embedded equivalent.
    """
    repository = await _build_repository(settings)
    storage = Storage(
        vectors=await _build_vectors(settings),
        lexical=await _build_lexical(settings),
        graph=await _build_graph(settings),
        objects=await _build_objects(settings),
        cache=await _build_cache(settings),
        repository=repository,
        settings=settings,
    )
    await _ensure_lexical_index(storage.lexical)
    log.info(
        "storage.ready",
        relational=repository.backend_name,
        vectors=storage.vectors.backend_name,
        lexical=storage.lexical.backend_name,
        graph=storage.graph.backend_name,
        objects=storage.objects.backend_name,
        cache=storage.cache.backend_name,
    )
    return storage


def describe_backends(settings: Settings) -> dict[str, str]:
    """The *configured* backend per store - what health reports compare against."""
    return {
        "relational": settings.relational_backend.value,
        "vector": settings.vector_backend.value,
        "lexical": settings.lexical_backend.value,
        "graph": settings.graph_backend.value,
        "object": settings.object_backend.value,
        "cache": settings.cache_backend.value,
    }


# -- per-store construction ----------------------------------------------
async def _build_vectors(settings: Settings) -> VectorStore:
    if settings.vector_backend is VectorBackend.EMBEDDED:
        return EmbeddedVectorStore(settings)

    def _distributed() -> VectorStore:
        from .backends.vector_qdrant import QdrantVectorStore

        return QdrantVectorStore(settings)

    return await _with_fallback("vectors", "qdrant", _distributed, lambda: EmbeddedVectorStore(settings))


async def _build_lexical(settings: Settings) -> LexicalStore:
    if settings.lexical_backend is LexicalBackend.EMBEDDED:
        return EmbeddedLexicalStore(settings)

    def _distributed() -> LexicalStore:
        from .backends.lexical_opensearch import OpenSearchLexicalStore

        return OpenSearchLexicalStore(settings)

    return await _with_fallback("lexical", "opensearch", _distributed, lambda: EmbeddedLexicalStore(settings))


async def _build_graph(settings: Settings) -> GraphStore:
    if settings.graph_backend is GraphBackend.EMBEDDED:
        return EmbeddedGraphStore(settings)

    def _distributed() -> GraphStore:
        from .backends.graph_neo4j import Neo4jGraphStore

        return Neo4jGraphStore(settings)

    return await _with_fallback("graph", "neo4j", _distributed, lambda: EmbeddedGraphStore(settings))


async def _build_objects(settings: Settings) -> ObjectStore:
    if settings.object_backend is ObjectBackend.FILESYSTEM:
        return FilesystemObjectStore(settings)

    def _distributed() -> ObjectStore:
        from .backends.object_s3 import S3ObjectStore

        return S3ObjectStore(settings)

    return await _with_fallback("objects", "s3", _distributed, lambda: FilesystemObjectStore(settings))


async def _build_cache(settings: Settings) -> CacheStore:
    if settings.cache_backend is CacheBackend.MEMORY:
        return MemoryCacheStore(settings)

    def _distributed() -> CacheStore:
        from .backends.cache_redis import RedisCacheStore

        return RedisCacheStore(settings)

    return await _with_fallback("cache", "redis", _distributed, lambda: MemoryCacheStore(settings))


async def _build_repository(settings: Settings) -> Repository:
    """PostgreSQL is probed by running the migration; SQLite is the fallback."""
    repository = SqlRepository(settings)
    try:
        await asyncio.wait_for(repository.initialise(), timeout=REPOSITORY_TIMEOUT_SECONDS)
        return repository
    except (Exception, asyncio.TimeoutError) as exc:
        if settings.relational_backend is RelationalBackend.SQLITE:
            log.error("storage.relational_unavailable", backend="sqlite", error=str(exc))
            raise
        await _safe_close(repository)
        _log_fallback("relational", "postgres", "sqlite", exc)
    embedded_settings = settings.model_copy(update={"relational_backend": RelationalBackend.SQLITE})
    fallback = SqlRepository(embedded_settings)
    await fallback.initialise()
    return fallback


# -- helpers --------------------------------------------------------------
async def _with_fallback(
    store: str,
    configured: str,
    distributed: Callable[[], T],
    embedded: Callable[[], T],
) -> T:
    """Build the distributed backend, or fall back to the embedded one and say why."""
    try:
        candidate = distributed()
    except Exception as exc:  # missing dependency or bad configuration
        _log_fallback(store, configured, "embedded", exc)
        return embedded()
    try:
        await asyncio.wait_for(_probe(candidate), timeout=PROBE_TIMEOUT_SECONDS)
        return candidate
    except (Exception, asyncio.TimeoutError) as exc:
        await _safe_close(candidate)
        _log_fallback(store, configured, "embedded", exc)
        return embedded()


async def _probe(candidate: Any) -> None:
    probe = getattr(candidate, "probe", None)
    if probe is None:
        raise AttributeError(f"{type(candidate).__name__} does not expose a reachability probe")
    await probe()


async def _safe_close(candidate: Any) -> None:
    try:
        await candidate.close()
    except Exception as exc:  # the backend is already broken; closing may fail too
        log.debug("storage.close_after_failure", store=type(candidate).__name__, error=str(exc))


def _log_fallback(store: str, configured: str, chosen: str, exc: BaseException) -> None:
    log.warning(
        "storage.backend_fallback",
        store=store,
        configured=configured,
        using=chosen,
        reason=f"{type(exc).__name__}: {exc}".strip(),
    )


async def _ensure_lexical_index(lexical: LexicalStore) -> None:
    """Create the shared lexical index up front so first-query search is not a 500."""
    try:
        await lexical.ensure_index(LEXICAL_INDEX)
    except Exception as exc:
        log.warning(
            "storage.lexical_index_unavailable",
            backend=lexical.backend_name,
            index=LEXICAL_INDEX,
            error=str(exc),
        )
