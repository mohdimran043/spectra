"""Application-facing entity-resolution service.

Wraps the cascade with caching, repository persistence and the cross-modal
queries the API and the Brain need.  The service owns *no* resolution logic - it
owns wiring, so the cascade stays unit-testable without storage.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any

from spectra_config import Settings
from spectra_config.logging import get_logger
from spectra_schemas import (
    CanonicalEntity,
    Chunk,
    EntityLink,
    EntityMention,
    EntityResolution,
    EntityType,
    Modality,
    PermissionContext,
)

from .extractor import EntityExtractor
from .resolver import DbLookup, EntityResolver

log = get_logger(__name__)

#: Resolutions are stable for as long as the entity index is: ten minutes keeps
#: hot investigation loops cheap without hiding a freshly ingested entity for long.
ENTITY_CACHE_TTL_SECONDS = 600
CACHE_PREFIX = "entity:resolve:v1"


class EntityResolutionService:
    """Resolve, search and traverse entities across every modality."""

    def __init__(
        self,
        *,
        storage: Any | None = None,
        gateway: Any | None = None,
        db_lookup: DbLookup | None = None,
        resolver: EntityResolver | None = None,
        extractor: EntityExtractor | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._storage = storage
        self._gateway = gateway
        self._db_lookup = db_lookup
        self._resolver = resolver
        self._extractor = extractor or EntityExtractor()
        self._settings = settings

    # -- wiring -----------------------------------------------------------
    async def _ensure(self) -> tuple[Any, EntityResolver]:
        if self._storage is None:
            from spectra_storage.facade import get_storage

            self._storage = await get_storage(self._settings)
        if self._gateway is None:
            self._gateway = await _maybe_gateway(self._settings)
        if self._resolver is None:
            self._resolver = EntityResolver(
                self._storage.repository,
                gateway=self._gateway,
                db_lookup=self._db_lookup,
                extractor=self._extractor,
            )
        return self._storage, self._resolver

    # -- resolution -------------------------------------------------------
    async def resolve(
        self,
        surface: str,
        ctx: PermissionContext | None = None,
        *,
        entity_type: EntityType | None = None,
        context: str = "",
    ) -> EntityResolution:
        """Resolve one surface form, serving repeat questions from the cache.

        Only *successful* resolutions are cached: an unresolved surface must be
        re-tried, because the entity it needs may have been ingested since.
        """
        storage, resolver = await self._ensure()
        key = self._cache_key(surface, entity_type)
        cached = await _cache_get(storage, key)
        if cached is not None:
            return EntityResolution.model_validate(cached)
        resolution = await resolver.resolve(surface, entity_type, context=context)
        if resolution.resolved is not None:
            await _cache_set(storage, key, resolution.model_dump(mode="json"))
        return resolution

    async def resolve_batch(
        self,
        surfaces: Sequence[str],
        ctx: PermissionContext | None = None,
        *,
        entity_type: EntityType | None = None,
    ) -> list[EntityResolution]:
        return [await self.resolve(surface, ctx, entity_type=entity_type) for surface in surfaces]

    async def extract_and_link(self, chunk: Chunk) -> tuple[list[CanonicalEntity], list[EntityLink]]:
        """Ingestion entry point: chunk text -> canonical entities + REFERS_TO edges."""
        _, resolver = await self._ensure()
        mentions = self.extract(chunk)
        entities = await resolver.merge_into_canonical(mentions)
        links = await resolver.link_mentions(chunk, mentions)
        storage, _ = await self._ensure()
        if links:
            await storage.repository.upsert_entity_links(links)
        log.debug("entity.chunk_linked", chunk_id=chunk.chunk_id, entities=len(entities), links=len(links))
        return entities, links

    @property
    def extractor(self) -> EntityExtractor:
        """The text-level extractor, shaped for `spectra_ingestion`'s protocol."""
        return self._extractor

    def extract(self, chunk: Chunk) -> list[EntityMention]:
        return self._extractor.extract(
            chunk.text,
            chunk.modality,
            chunk_id=chunk.chunk_id,
            asset_id=chunk.asset_id,
            source_id=chunk.source_id,
        )

    # -- queries ----------------------------------------------------------
    async def search_entities(self, text: str, limit: int = 20) -> list[CanonicalEntity]:
        storage, _ = await self._ensure()
        return await storage.repository.search_entities(text, limit=limit)

    async def get_entity(self, entity_id: str) -> CanonicalEntity | None:
        storage, _ = await self._ensure()
        return await storage.repository.get_entity(entity_id)

    async def entities_for_chunk(self, chunk_id: str) -> list[CanonicalEntity]:
        storage, _ = await self._ensure()
        links = await storage.repository.links_for_chunk(chunk_id)
        entities = [await storage.repository.get_entity(link.entity_id) for link in links]
        return [entity for entity in entities if entity is not None]

    async def cross_modal_links(self, entity_id: str, limit: int = 200) -> dict[Modality, list[EntityLink]]:
        """Every modality that references ``entity_id``, grouped by modality."""
        storage, _ = await self._ensure()
        links = await storage.repository.links_for_entity(entity_id, limit=limit)
        grouped: dict[Modality, list[EntityLink]] = {}
        for link in links:
            grouped.setdefault(link.modality, []).append(link)
        return grouped

    # -- helpers ----------------------------------------------------------
    def _cache_key(self, surface: str, entity_type: EntityType | None) -> str:
        signature = _index_signature(self._gateway)
        payload = json.dumps(
            {"surface": surface, "type": entity_type.value if entity_type else None, "index": signature},
            sort_keys=True,
            default=str,
        )
        return f"{CACHE_PREFIX}:{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:32]}"


async def _maybe_gateway(settings: Settings | None) -> Any | None:
    """The gateway is optional: semantic and LLM steps degrade, the rest still work."""
    try:
        from spectra_ai_core.gateway import get_gateway

        return await get_gateway(settings)
    except Exception as exc:  # noqa: BLE001 - model runtime unavailability is expected
        log.warning("entity.gateway_unavailable", error=str(exc))
        return None


def _index_signature(gateway: Any | None) -> str:
    if gateway is None:
        return "no-gateway"
    try:
        return json.dumps(gateway.index_signature(), sort_keys=True, default=str)
    except Exception:  # noqa: BLE001 - signature is advisory for the cache key
        return "unknown"


async def _cache_get(storage: Any, key: str) -> Any | None:
    try:
        return await storage.cache.get(key)
    except Exception as exc:  # noqa: BLE001 - a cache outage must never fail a resolution
        log.warning("entity.cache_get_failed", error=str(exc))
        return None


async def _cache_set(storage: Any, key: str, value: Any) -> None:
    try:
        await storage.cache.set(key, value, ttl_seconds=ENTITY_CACHE_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001 - see above
        log.warning("entity.cache_set_failed", error=str(exc))
