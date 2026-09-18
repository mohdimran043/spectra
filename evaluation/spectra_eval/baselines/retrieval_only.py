"""The three non-agentic baselines: BM25, vector RAG, multimodal RAG.

All three share one shape - retrieve, concatenate, answer - and differ only in
which retrievers they are permitted to use.  That is what isolates the value of
each retrieval signal before any agency is added.
"""

from __future__ import annotations

from spectra_schemas import Modality, PermissionContext, SearchMode, SearchRequest

from ..datasets.benchmark import BenchmarkQuestion
from .base import Baseline, BaselineResult, hits_to_targets, snippet_answer

TOP_K = 10


class _RetrievalBaseline(Baseline):
    """Shared retrieve-and-concatenate behaviour."""

    rerank = False
    modalities: tuple[Modality, ...] = ()

    async def answer(self, question: BenchmarkQuestion, ctx: PermissionContext) -> BaselineResult:
        search = self.container.search
        if search is None:
            return BaselineResult(question_id=question.id, status="failed",
                                  error="the search service is unavailable")
        request = SearchRequest(
            query=question.question,
            mode=SearchMode.FAST,
            top_k=TOP_K,
            rerank=self.rerank,
        )
        if self.modalities:
            request = request.model_copy(
                update={"filters": request.filters.model_copy(update={"modalities": list(self.modalities)})}
            )
        response = await self._retrieve(search, request, ctx)
        hits = response.hits[:TOP_K]
        return BaselineResult(
            question_id=question.id,
            answer=snippet_answer(hits),
            status="supported" if hits else "insufficient_evidence",
            confidence=hits[0].score if hits else 0.0,
            targets=hits_to_targets(hits),
            entities=sorted({e for hit in hits for e in hit.entities}),
            evidence_labels=[f"E{i}" for i in range(1, min(len(hits), 3) + 1)],
            latency_ms=response.latency_ms,
            tool_calls=1,
            degraded=response.degraded,
        )

    async def _retrieve(self, search, request, ctx):
        return await search.search(request, ctx)


class Bm25Baseline(_RetrievalBaseline):
    name = "bm25"
    description = "Lexical BM25 retrieval only"
    lacks = ("semantics", "multimodality", "agency", "verification")

    async def _retrieve(self, search, request, ctx):
        # Lexical-only is expressed by disabling rerank and letting the fusion
        # stage see just the BM25 list; the service exposes this as a flag.
        return await search.search(request.model_copy(update={"rerank": False}), ctx,
                                   retrievers=("lexical",)) if _accepts_retrievers(search) \
            else await search.search(request.model_copy(update={"rerank": False}), ctx)


def _accepts_retrievers(search) -> bool:
    import inspect

    try:
        return "retrievers" in inspect.signature(search.search).parameters
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return False


class VectorRagBaseline(_RetrievalBaseline):
    name = "vector_rag"
    description = "Dense retrieval plus concatenation"
    lacks = ("lexical precision on identifiers", "agency", "verification")
    modalities = (Modality.DOCUMENT, Modality.AUDIO, Modality.VIDEO, Modality.DATABASE)


class MultimodalRagBaseline(_RetrievalBaseline):
    name = "multimodal_rag"
    description = "Dense plus multimodal retrieval, reranked, still no agent"
    lacks = ("agency", "claim grounding", "disproof", "verification")
    rerank = True
