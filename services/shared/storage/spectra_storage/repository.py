"""Relational repository interface - the control-plane data access seam.

Backed by SQLite in development and PostgreSQL in production; callers only ever
see this interface.  The *enterprise demo* business tables (customers,
transactions, incidents, assets) deliberately live in a SEPARATE database that
is reached through the database connector, so "query a real database" is a
genuine external-source path and not a privileged internal shortcut.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from typing import Any

from spectra_schemas import (
    Asset,
    CanonicalEntity,
    Chunk,
    EntityLink,
    IndexVersion,
    IngestJob,
    SearchHistoryEntry,
    SourceDescriptor,
)


class Repository(ABC):
    """CRUD over the SPECTRA control plane."""

    backend_name: str = "abstract"

    # -- lifecycle --------------------------------------------------------
    @abstractmethod
    async def initialise(self) -> None:
        """Create schema if absent and apply pending migrations."""

    @abstractmethod
    async def health(self) -> dict[str, Any]: ...

    @abstractmethod
    async def close(self) -> None: ...

    # -- sources ----------------------------------------------------------
    @abstractmethod
    async def upsert_source(self, source: SourceDescriptor) -> SourceDescriptor: ...

    @abstractmethod
    async def get_source(self, source_id: str) -> SourceDescriptor | None: ...

    @abstractmethod
    async def list_sources(self) -> list[SourceDescriptor]: ...

    @abstractmethod
    async def delete_source(self, source_id: str) -> bool: ...

    # -- assets -----------------------------------------------------------
    @abstractmethod
    async def upsert_asset(self, asset: Asset) -> Asset: ...

    @abstractmethod
    async def get_asset(self, asset_id: str) -> Asset | None: ...

    @abstractmethod
    async def list_assets(
        self, source_id: str | None = None, kind: str | None = None, limit: int = 200, offset: int = 0
    ) -> list[Asset]: ...

    @abstractmethod
    async def count_assets(self, source_id: str | None = None) -> int: ...

    @abstractmethod
    async def find_asset_by_hash(self, content_hash: str) -> Asset | None: ...

    # -- chunks -----------------------------------------------------------
    @abstractmethod
    async def upsert_chunks(self, chunks: Sequence[Chunk]) -> int: ...

    @abstractmethod
    async def get_chunk(self, chunk_id: str) -> Chunk | None: ...

    @abstractmethod
    async def get_chunks(self, chunk_ids: Sequence[str]) -> list[Chunk]: ...

    @abstractmethod
    async def list_chunks_by_asset(self, asset_id: str) -> list[Chunk]: ...

    @abstractmethod
    async def iter_chunks(self, batch_size: int = 500) -> AsyncIterator[list[Chunk]]: ...

    @abstractmethod
    async def count_chunks(self, modality: str | None = None) -> int: ...

    @abstractmethod
    async def delete_chunks_for_asset(self, asset_id: str) -> int: ...

    # -- entities ---------------------------------------------------------
    @abstractmethod
    async def upsert_entity(self, entity: CanonicalEntity) -> CanonicalEntity: ...

    @abstractmethod
    async def get_entity(self, entity_id: str) -> CanonicalEntity | None: ...

    @abstractmethod
    async def find_entities_by_key(self, normalized_key: str) -> list[CanonicalEntity]: ...

    @abstractmethod
    async def list_entities(
        self, entity_type: str | None = None, limit: int = 200, offset: int = 0
    ) -> list[CanonicalEntity]: ...

    @abstractmethod
    async def search_entities(self, text: str, limit: int = 20) -> list[CanonicalEntity]: ...

    @abstractmethod
    async def upsert_entity_links(self, links: Sequence[EntityLink]) -> int: ...

    @abstractmethod
    async def links_for_entity(self, entity_id: str, limit: int = 200) -> list[EntityLink]: ...

    @abstractmethod
    async def links_for_chunk(self, chunk_id: str) -> list[EntityLink]: ...

    # -- ingest jobs ------------------------------------------------------
    @abstractmethod
    async def upsert_job(self, job: IngestJob) -> IngestJob: ...

    @abstractmethod
    async def get_job(self, job_id: str) -> IngestJob | None: ...

    @abstractmethod
    async def list_jobs(self, limit: int = 50) -> list[IngestJob]: ...

    # -- search history ---------------------------------------------------
    @abstractmethod
    async def record_search(self, entry: SearchHistoryEntry) -> None: ...

    @abstractmethod
    async def list_searches(self, limit: int = 50) -> list[SearchHistoryEntry]: ...

    @abstractmethod
    async def clear_searches(self) -> int: ...

    # -- index versioning -------------------------------------------------
    @abstractmethod
    async def record_index_version(self, version: IndexVersion) -> None: ...

    @abstractmethod
    async def active_index_version(self) -> IndexVersion | None: ...

    @abstractmethod
    async def list_index_versions(self) -> list[IndexVersion]: ...

    # -- audit ------------------------------------------------------------
    @abstractmethod
    async def stats(self) -> dict[str, int]: ...
