"""The five-stage retrieval pipeline.

Each stage is a small, mostly pure function that takes the previous stage's
output and returns ``(payload, RetrievalStageStat)``.  Nothing here holds state,
so the pipeline can be run, traced and unit-tested stage by stage - which is what
the Search Autopsy view renders.

    1. candidate generation  (parallel: exact-id, BM25, dense ANN, multimodal ANN)
    2. filtering             (source / time / entity / type / media + PERMISSIONS)
    3. fusion + reranking    (RRF, then a cross-encoder on the top-k only)
    4. scoring               (UnifiedScorer - weighted, normalised, explainable)
    5. assembly              (snippets, provenance, score breakdown)
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from spectra_config.budgets import SearchBudget
from spectra_config.logging import get_logger
from spectra_schemas import (
    Chunk,
    Modality,
    PermissionContext,
    RetrievalStageStat,
    SearchHit,
    SearchRequest,
    SourceDescriptor,
)

from .assembly import build_hit
from .candidates import Candidate, FusedCandidate, renumber, rrf_fuse
from .filters import REJECT_PERMISSION, rejection_reason, store_filters
from .retrievers import (
    RetrieverOutcome,
    dense_candidates,
    entity_link_candidates,
    exact_id_candidates,
    lexical_candidates,
    multimodal_candidates,
)
from .scoring import ScoredCandidate, ScoreInput, UnifiedScorer
from .snippets import query_terms

log = get_logger(__name__)

STAGE_CANDIDATES = "candidate_generation"
STAGE_FILTER = "filtering"
STAGE_FUSION = "fusion_rerank"
STAGE_SCORING = "scoring"
STAGE_ASSEMBLY = "assembly"

#: Modalities whose chunks live in the multimodal collection.
VISUAL_MODALITIES = frozenset({Modality.IMAGE, Modality.VIDEO})


@dataclass(frozen=True)
class StageContext:
    """Everything the stages need, injected once per search."""

    storage: Any
    gateway: Any | None
    budget: SearchBudget
    permissions: PermissionContext
    scorer: UnifiedScorer


@dataclass(frozen=True)
class CandidateStage:
    lists: Mapping[str, tuple[Candidate, ...]]
    entity_ids: tuple[str, ...] = ()
    degraded_reasons: tuple[str, ...] = ()

    @property
    def total(self) -> int:
        return sum(len(values) for values in self.lists.values())


@dataclass(frozen=True)
class FilteredStage:
    lists: Mapping[str, tuple[Candidate, ...]]
    chunks: Mapping[str, Chunk]
    sources: Mapping[str, SourceDescriptor]
    dropped_permission: int = 0
    dropped_filter: int = 0
    dropped_missing: int = 0


@dataclass(frozen=True)
class FusionStage:
    fused: tuple[FusedCandidate, ...]
    rerank_scores: Mapping[str, float] = field(default_factory=dict)
    reranked: bool = False
    degraded_reasons: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Stage 1 - candidate generation
# ---------------------------------------------------------------------------
async def generate_candidates(
    request: SearchRequest,
    stage: StageContext,
    *,
    image_bytes: bytes | None = None,
    extra_entity_ids: Sequence[str] = (),
) -> tuple[CandidateStage, RetrievalStageStat]:
    """Run every applicable retriever in parallel over pre-built indexes only."""
    started = time.perf_counter()
    pool = stage.budget.candidate_pool_size
    pushdown = store_filters(request.filters)
    tasks: list[Any] = [
        exact_id_candidates(request.query, stage.storage, pool),
        lexical_candidates(request.query, stage.storage, pushdown, pool),
        dense_candidates(request.query, stage.storage, stage.gateway, pushdown, pool),
    ]
    if _wants_multimodal(request, image_bytes):
        tasks.append(
            multimodal_candidates(
                request.query, stage.storage, stage.gateway, pushdown, pool, image_bytes=image_bytes
            )
        )
    if extra_entity_ids:
        tasks.append(entity_link_candidates(stage.storage, extra_entity_ids, pool))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    outcomes = _flatten_outcomes(results)
    lists = _merge_outcomes(outcomes)
    entity_ids = tuple(
        entity_id
        for outcome in outcomes
        for entity_id in outcome.extra.get("entity_ids", ())
    )
    payload = CandidateStage(
        lists=lists,
        entity_ids=entity_ids,
        degraded_reasons=tuple(o.degraded_reason for o in outcomes if o.degraded_reason),
    )
    detail = " ".join(f"{o.name}={o.count}" for o in outcomes)
    return payload, RetrievalStageStat(
        stage=STAGE_CANDIDATES,
        candidates_in=0,
        candidates_out=payload.total,
        latency_ms=_elapsed(started),
        detail=detail or "no retrievers ran",
    )


# ---------------------------------------------------------------------------
# Stage 2 - filtering (including permissions)
# ---------------------------------------------------------------------------
async def filter_candidates(
    candidates: CandidateStage, request: SearchRequest, stage: StageContext
) -> tuple[FilteredStage, RetrievalStageStat]:
    """Hydrate chunks, then drop everything this role may not read or did not ask for."""
    started = time.perf_counter()
    chunk_ids = _unique(chunk_id for values in candidates.lists.values() for chunk_id in (c.chunk_id for c in values))
    chunks = {chunk.chunk_id: chunk for chunk in await stage.storage.repository.get_chunks(chunk_ids)}
    sources = await _source_map(stage.storage)

    allowed, dropped = _partition(chunk_ids, chunks, request, stage, sources)
    filtered_lists = {
        name: renumber([c for c in values if c.chunk_id in allowed])
        for name, values in candidates.lists.items()
    }
    payload = FilteredStage(
        lists={name: values for name, values in filtered_lists.items() if values},
        chunks=allowed,
        sources=sources,
        dropped_permission=dropped["permission"],
        dropped_filter=dropped["filter"],
        dropped_missing=len(chunk_ids) - len(chunks),
    )
    log.debug(
        "search.filtered",
        kept=len(allowed),
        dropped_permission=payload.dropped_permission,
        dropped_filter=payload.dropped_filter,
        role=stage.permissions.role.value,
    )
    return payload, RetrievalStageStat(
        stage=STAGE_FILTER,
        candidates_in=len(chunk_ids),
        candidates_out=len(allowed),
        latency_ms=_elapsed(started),
        detail=(
            f"permission_denied={payload.dropped_permission} filtered={payload.dropped_filter} "
            f"missing_chunk={payload.dropped_missing} role={stage.permissions.role.value}"
        ),
    )


# ---------------------------------------------------------------------------
# Stage 3 - fusion + reranking
# ---------------------------------------------------------------------------
async def fuse_and_rerank(
    filtered: FilteredStage, request: SearchRequest, stage: StageContext
) -> tuple[FusionStage, RetrievalStageStat]:
    """RRF the retriever lists, then cross-encode only the top ``rerank_top_k``."""
    started = time.perf_counter()
    fused = rrf_fuse(filtered.lists)
    if not fused:
        return FusionStage(fused=()), RetrievalStageStat(
            stage=STAGE_FUSION, candidates_in=0, candidates_out=0, latency_ms=_elapsed(started),
            detail="no candidates to fuse",
        )
    window = fused[: stage.budget.rerank_top_k]
    if not request.rerank or stage.gateway is None:
        reason = "reranking disabled by request" if not request.rerank else "reranker unavailable: no gateway"
        payload = FusionStage(fused=fused, reranked=False, degraded_reasons=(reason,))
        return payload, _fusion_stat(started, fused, window, payload)

    texts = [filtered.chunks[item.chunk_id].text for item in window]
    scores, reason = await _rerank(stage.gateway, request.query, texts)
    payload = FusionStage(
        fused=fused,
        rerank_scores={item.chunk_id: score for item, score in zip(window, scores, strict=False)} if scores else {},
        reranked=bool(scores),
        degraded_reasons=(reason,) if reason else (),
    )
    return payload, _fusion_stat(started, fused, window, payload)


# ---------------------------------------------------------------------------
# Stage 4 - unified scoring
# ---------------------------------------------------------------------------
def score_candidates(
    fusion: FusionStage, filtered: FilteredStage, request: SearchRequest, stage: StageContext
) -> tuple[tuple[ScoredCandidate, ...], RetrievalStageStat]:
    """Combine every signal into one explainable score."""
    started = time.perf_counter()
    inputs = [
        ScoreInput(
            fused=item,
            chunk=filtered.chunks[item.chunk_id],
            source=filtered.sources.get(filtered.chunks[item.chunk_id].source_id),
            rerank=fusion.rerank_scores.get(item.chunk_id) if fusion.reranked else None,
        )
        for item in fusion.fused
        if item.chunk_id in filtered.chunks
    ]
    scored = stage.scorer.score(inputs, filters=request.filters, reranked=fusion.reranked)
    exact = sum(1 for row in scored if row.is_exact)
    return scored, RetrievalStageStat(
        stage=STAGE_SCORING,
        candidates_in=len(inputs),
        candidates_out=len(scored),
        latency_ms=_elapsed(started),
        detail=f"exact_id_hits={exact} reranked={fusion.reranked}",
    )


# ---------------------------------------------------------------------------
# Stage 5 - assembly
# ---------------------------------------------------------------------------
async def assemble_hits(
    scored: Sequence[ScoredCandidate], request: SearchRequest, stage: StageContext
) -> tuple[tuple[SearchHit, ...], RetrievalStageStat]:
    """Build the returned hits: real snippets, real provenance, full breakdown."""
    started = time.perf_counter()
    top = list(scored[: max(1, request.top_k)])
    assets = await _asset_map(stage.storage, _unique(row.chunk.asset_id for row in top))
    terms = query_terms(request.query, tuple(_exact_terms(top)))
    hits = tuple(
        build_hit(row, assets.get(row.chunk.asset_id), terms, include_text=request.include_text)
        for row in top
    )
    return hits, RetrievalStageStat(
        stage=STAGE_ASSEMBLY,
        candidates_in=len(scored),
        candidates_out=len(hits),
        latency_ms=_elapsed(started),
        detail=f"assets_loaded={len(assets)} terms={len(terms)}",
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _partition(
    chunk_ids: Sequence[str],
    chunks: Mapping[str, Chunk],
    request: SearchRequest,
    stage: StageContext,
    sources: Mapping[str, SourceDescriptor],
) -> tuple[dict[str, Chunk], dict[str, int]]:
    """Split hydrated candidates into readable-and-wanted vs dropped."""
    allowed: dict[str, Chunk] = {}
    dropped = {"permission": 0, "filter": 0}
    for chunk_id in chunk_ids:
        chunk = chunks.get(chunk_id)
        if chunk is None:
            continue
        reason = rejection_reason(chunk, request.filters, stage.permissions, sources.get(chunk.source_id))
        if reason is None:
            allowed[chunk_id] = chunk
            continue
        dropped["permission" if reason == REJECT_PERMISSION else "filter"] += 1
    return allowed, dropped


def _wants_multimodal(request: SearchRequest, image_bytes: bytes | None) -> bool:
    if image_bytes is not None or request.image_asset_id:
        return True
    modalities = set(request.filters.modalities)
    return not modalities or bool(modalities & VISUAL_MODALITIES)


def _flatten_outcomes(results: Sequence[Any]) -> list[RetrieverOutcome]:
    outcomes: list[RetrieverOutcome] = []
    for result in results:
        if isinstance(result, BaseException):
            log.warning("search.retriever_crashed", error=str(result))
            continue
        if isinstance(result, tuple):
            outcomes.extend(result)
        else:
            outcomes.append(result)
    return outcomes


def _merge_outcomes(outcomes: Sequence[RetrieverOutcome]) -> dict[str, tuple[Candidate, ...]]:
    merged: dict[str, list[Candidate]] = {}
    for outcome in outcomes:
        if outcome.candidates:
            merged.setdefault(outcome.name, []).extend(outcome.candidates)
    return {name: renumber(values) for name, values in merged.items()}


async def _rerank(gateway: Any, query: str, texts: Sequence[str]) -> tuple[list[float], str | None]:
    if not texts:
        return [], None
    try:
        result = await gateway.rerank(query, list(texts))
    except Exception as exc:  # noqa: BLE001 - degrade to fused order, never fail the search
        log.warning("search.rerank_failed", error=str(exc))
        return [], f"reranker unavailable: {exc}; degraded to fused (RRF) order"
    if result.degraded:
        return [], f"reranker degraded: {result.degraded_reason}; degraded to fused (RRF) order"
    return [float(score) for score in result.scores], None


def _fusion_stat(
    started: float, fused: Sequence[FusedCandidate], window: Sequence[FusedCandidate], payload: FusionStage
) -> RetrievalStageStat:
    return RetrievalStageStat(
        stage=STAGE_FUSION,
        candidates_in=len(fused),
        candidates_out=len(fused),
        latency_ms=_elapsed(started),
        detail=(
            f"rrf_pool={len(fused)} rerank_window={len(window)} reranked={payload.reranked}"
            + (f" ({'; '.join(payload.degraded_reasons)})" if payload.degraded_reasons else "")
        ),
    )


async def _source_map(storage: Any) -> dict[str, SourceDescriptor]:
    try:
        sources = await storage.repository.list_sources()
    except Exception as exc:  # noqa: BLE001 - without descriptors we fall back to chunk permissions
        log.warning("search.sources_unavailable", error=str(exc))
        return {}
    return {source.source_id: source for source in sources}


async def _asset_map(storage: Any, asset_ids: Sequence[str]) -> dict[str, Any]:
    assets = await asyncio.gather(
        *(storage.repository.get_asset(asset_id) for asset_id in asset_ids), return_exceptions=True
    )
    return {
        asset_id: asset
        for asset_id, asset in zip(asset_ids, assets, strict=False)
        if asset is not None and not isinstance(asset, BaseException)
    }


def _exact_terms(rows: Sequence[ScoredCandidate]) -> list[str]:
    return [entity for row in rows if row.is_exact for entity in row.chunk.entities]


def _unique(values: Any) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        seen.setdefault(value, None)
    return list(seen)


def _elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 3)
