"""``SearchService`` - the staged retrieval pipeline as one callable service.

Nothing above this layer knows which stores or models are active, and nothing
below it knows who is asking: the :class:`PermissionContext` is threaded through
every stage and baked into every cache key.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

from spectra_ai_core.phase import query_phase
from spectra_config import Settings, get_settings
from spectra_config.budgets import SearchBudget, budget_for
from spectra_config.logging import get_logger
from spectra_schemas import (
    Modality,
    PermissionContext,
    RetrievalStageStat,
    SearchFilters,
    SearchHit,
    SearchMode,
    SearchRequest,
    SearchResponse,
)

from .cache import build_cache_key, cache_get, cache_set, index_identity
from .scoring import ScoringWeights, UnifiedScorer
from .stages import (
    StageContext,
    assemble_hits,
    filter_candidates,
    fuse_and_rerank,
    generate_candidates,
    score_candidates,
)

log = get_logger(__name__)

SEARCH_CAPABILITY = "search"
STAGE_CACHE = "cache"

#: Text pulled from an image asset's own chunks (caption / OCR) and used as the
#: textual half of an image->everything query.  Capped so one verbose caption
#: cannot blow up the query embedding.
IMAGE_QUERY_TEXT_CHARS = 512


class SearchService:
    """Staged, permission-aware, index-only retrieval."""

    def __init__(
        self,
        *,
        storage: Any | None = None,
        gateway: Any | None = None,
        settings: Settings | None = None,
        scorer: UnifiedScorer | None = None,
    ) -> None:
        self._storage = storage
        self._gateway = gateway
        self._settings = settings or get_settings()
        self._scorer = scorer or UnifiedScorer(ScoringWeights.from_settings(self._settings))

    # -- public API -------------------------------------------------------
    async def search(self, request: SearchRequest, ctx: PermissionContext) -> SearchResponse:
        """Run the five-stage pipeline for ``request`` on behalf of ``ctx``.

        Runs inside the query phase, so any attempt to OCR, transcribe or caption
        a raw object from here raises rather than silently making query cost grow
        with corpus size.
        """
        async with query_phase():
            return await self._search(request, ctx)

    async def _search(self, request: SearchRequest, ctx: PermissionContext) -> SearchResponse:
        _require_search(ctx)
        storage, gateway = await self._ensure()
        started = time.perf_counter()
        version, signature = await index_identity(storage, gateway)
        key = build_cache_key(request, ctx, index_version=version, index_signature=signature)
        cached = await cache_get(storage, key)
        if cached is not None:
            return _with_cache_stat(cached, started)

        response = await self._pipeline(request, ctx, storage, gateway, started)
        await cache_set(storage, key, response)
        return response

    async def search_modality(
        self,
        query: str | SearchRequest,
        modality: Modality | None,
        ctx: PermissionContext,
        *,
        mode: SearchMode = SearchMode.FAST,
        top_k: int = 20,
        filters: SearchFilters | None = None,
        include_text: bool = False,
        rerank: bool = True,
    ) -> SearchResponse:
        """Search one modality (or all when ``modality`` is None).

        ``query`` accepts either raw text or a complete ``SearchRequest``.  The
        agent already has a fully-formed request - mode, top_k and filters
        included - so re-deriving those from defaults would silently discard
        the budget it chose.
        """
        if isinstance(query, SearchRequest):
            base = query.filters if filters is None else filters
            scoped = base.model_copy(
                update={"modalities": [modality] if modality else list(base.modalities)}
            )
            return await self.search(query.model_copy(update={"filters": scoped}), ctx)

        base = filters or SearchFilters()
        scoped = base.model_copy(update={"modalities": [modality] if modality else list(base.modalities)})
        request = SearchRequest(
            query=query, mode=mode, filters=scoped, top_k=top_k, include_text=include_text, rerank=rerank
        )
        return await self.search(request, ctx)

    async def search_documents(self, query: str, ctx: PermissionContext, **kwargs: Any) -> SearchResponse:
        return await self.search_modality(query, Modality.DOCUMENT, ctx, **kwargs)

    async def search_images(self, query: str, ctx: PermissionContext, **kwargs: Any) -> SearchResponse:
        return await self.search_modality(query, Modality.IMAGE, ctx, **kwargs)

    async def search_videos(self, query: str, ctx: PermissionContext, **kwargs: Any) -> SearchResponse:
        return await self.search_modality(query, Modality.VIDEO, ctx, **kwargs)

    async def search_audio(self, query: str, ctx: PermissionContext, **kwargs: Any) -> SearchResponse:
        return await self.search_modality(query, Modality.AUDIO, ctx, **kwargs)

    async def search_all(self, query: str, ctx: PermissionContext, **kwargs: Any) -> SearchResponse:
        return await self.search_modality(query, None, ctx, **kwargs)

    async def search_by_image(
        self,
        asset_id: str,
        ctx: PermissionContext,
        *,
        mode: SearchMode = SearchMode.FAST,
        top_k: int = 20,
        filters: SearchFilters | None = None,
    ) -> SearchResponse:
        """Image -> everything.

        Reads the image's *stored* OCR / caption text and entity links, then runs
        BOTH a multimodal ANN (on the image's own embedding input) and an
        entity-driven lookup, merging the two candidate sets in one fusion pass.
        """
        _require_search(ctx)
        storage, gateway = await self._ensure()
        started = time.perf_counter()
        asset = await storage.repository.get_asset(asset_id)
        if asset is None:
            raise ValueError(f"unknown asset: {asset_id}")
        text, entity_ids = await self._image_context(storage, asset_id)
        request = SearchRequest(
            query=text,
            mode=mode,
            filters=filters or SearchFilters(),
            top_k=top_k,
            image_asset_id=asset_id,
        )
        version, signature = await index_identity(storage, gateway)
        key = build_cache_key(request, ctx, index_version=version, index_signature=signature)
        cached = await cache_get(storage, key)
        if cached is not None:
            return _with_cache_stat(cached, started)
        image_bytes = await _object_bytes(storage, asset.object_uri)
        response = await self._pipeline(
            request, ctx, storage, gateway, started, image_bytes=image_bytes, extra_entity_ids=entity_ids
        )
        await cache_set(storage, key, response)
        return response

    @property
    def scorer(self) -> UnifiedScorer:
        return self._scorer

    def explain(self, hit: SearchHit) -> str:
        return self._scorer.explain(hit)

    # -- pipeline ---------------------------------------------------------
    async def _pipeline(
        self,
        request: SearchRequest,
        ctx: PermissionContext,
        storage: Any,
        gateway: Any | None,
        started: float,
        *,
        image_bytes: bytes | None = None,
        extra_entity_ids: Sequence[str] = (),
    ) -> SearchResponse:
        budget = self._budget(request.mode)
        stage = StageContext(
            storage=storage, gateway=gateway, budget=budget, permissions=ctx, scorer=self._scorer
        )
        candidates, stat_one = await generate_candidates(
            request, stage, image_bytes=image_bytes, extra_entity_ids=extra_entity_ids
        )
        filtered, stat_two = await filter_candidates(candidates, request, stage)
        fusion, stat_three = await fuse_and_rerank(filtered, request, stage)
        scored, stat_four = score_candidates(fusion, filtered, request, stage)
        hits, stat_five = await assemble_hits(scored, request, stage)

        reasons = _degraded_reasons(candidates.degraded_reasons, fusion.degraded_reasons, gateway)
        response = SearchResponse(
            query=request.query,
            mode=request.mode,
            hits=list(hits),
            total_candidates=candidates.total,
            stages=[stat_one, stat_two, stat_three, stat_four, stat_five],
            latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
            degraded=bool(reasons),
            degraded_reasons=list(reasons),
            entities=_entities_of(hits),
        )
        log.info(
            "search.completed",
            query=request.query[:120],
            mode=request.mode.value,
            hits=len(hits),
            candidates=candidates.total,
            degraded=response.degraded,
            latency_ms=response.latency_ms,
        )
        return response

    # -- wiring -----------------------------------------------------------
    async def _ensure(self) -> tuple[Any, Any | None]:
        if self._storage is None:
            from spectra_storage.facade import get_storage

            self._storage = await get_storage(self._settings)
        if self._gateway is None:
            self._gateway = await _maybe_gateway(self._settings)
        return self._storage, self._gateway

    def _budget(self, mode: SearchMode) -> SearchBudget:
        return budget_for(mode.value, self._settings)

    async def _image_context(self, storage: Any, asset_id: str) -> tuple[str, tuple[str, ...]]:
        """The image's stored caption/OCR text and every entity linked to it."""
        chunks = await storage.repository.list_chunks_by_asset(asset_id)
        text = " ".join(chunk.text for chunk in chunks if chunk.text).strip()[:IMAGE_QUERY_TEXT_CHARS]
        entity_ids: list[str] = []
        for chunk in chunks:
            entity_ids.extend(chunk.entities)
            links = await storage.repository.links_for_chunk(chunk.chunk_id)
            entity_ids.extend(link.entity_id for link in links)
        unique = list(dict.fromkeys(entity_ids))
        log.debug("search.image_context", asset_id=asset_id, chars=len(text), entities=len(unique))
        return text, tuple(unique)


def _require_search(ctx: PermissionContext) -> None:
    if not ctx.can(SEARCH_CAPABILITY):
        raise PermissionError(f"role {ctx.role.value!r} may not search")


def _degraded_reasons(
    candidate_reasons: Sequence[str], fusion_reasons: Sequence[str], gateway: Any | None
) -> tuple[str, ...]:
    reasons = [*candidate_reasons, *fusion_reasons]
    if gateway is None:
        reasons.append("model gateway unavailable: lexical and exact-id retrieval only")
    else:
        reasons.extend(_gateway_reasons(gateway))
    return tuple(dict.fromkeys(reason for reason in reasons if reason))


def _gateway_reasons(gateway: Any) -> list[str]:
    try:
        return list(gateway.degraded_reasons())
    except Exception as exc:  # noqa: BLE001 - introspection must never fail a search
        log.warning("search.degraded_reasons_failed", error=str(exc))
        return []


def _entities_of(hits: Sequence[SearchHit]) -> list[str]:
    seen: dict[str, None] = {}
    for hit in hits:
        for entity in hit.entities:
            seen.setdefault(entity, None)
    return list(seen)


def _with_cache_stat(response: SearchResponse, started: float) -> SearchResponse:
    """Return the cached response, re-timed and marked as a cache hit."""
    elapsed = round((time.perf_counter() - started) * 1000.0, 3)
    stat = RetrievalStageStat(
        stage=STAGE_CACHE,
        candidates_in=len(response.hits),
        candidates_out=len(response.hits),
        latency_ms=elapsed,
        detail="cache hit",
    )
    return response.model_copy(update={"latency_ms": elapsed, "stages": [stat, *response.stages]})


async def _maybe_gateway(settings: Settings | None) -> Any | None:
    try:
        from spectra_ai_core.gateway import get_gateway

        return await get_gateway(settings)
    except Exception as exc:  # noqa: BLE001 - model runtime absence is a degradation, not a failure
        log.warning("search.gateway_unavailable", error=str(exc))
        return None


async def _object_bytes(storage: Any, object_uri: str) -> bytes | None:
    """Fetch the query image itself.  One object read, never a corpus scan."""
    try:
        return await storage.objects.get(object_uri)
    except Exception as exc:  # noqa: BLE001 - fall back to the caption-driven path
        log.warning("search.object_unavailable", uri=object_uri, error=str(exc))
        return None
