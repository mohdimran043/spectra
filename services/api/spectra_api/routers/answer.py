"""Ask a question, get a short cited answer over the search results."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field
from spectra_schemas import SearchFilters, SearchMode, SearchRequest, SearchResponse

from .. import history
from ..answering import MAX_CITED_HITS, answer_from_hits
from ..dependencies import Container, Ctx, service_or_503

router = APIRouter(tags=["answer"])


class AnswerRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    mode: SearchMode = SearchMode.FAST
    top_k: int = Field(default=MAX_CITED_HITS, ge=1, le=20)
    #: Restrict the search to these sources. Empty means every source the
    #: caller is permitted to read.
    source_ids: list[str] = Field(default_factory=list)


class AnswerResponse(BaseModel):
    """The answer and the results it was written from.

    ``answer`` is empty whenever nothing could honestly be said - no results, no
    generative runtime, or a generated answer that cited nothing retrieved. The
    results stand on their own in every case.
    """

    query: str
    answer: str = ""
    citations: list[int] = Field(default_factory=list)
    model: str = ""
    degraded: bool = False
    degraded_reason: str | None = None
    results: SearchResponse


@router.post("/answer", response_model=AnswerResponse)
async def answer(body: AnswerRequest, container: Container, ctx: Ctx) -> AnswerResponse:
    service = service_or_503(container, "search")
    request = SearchRequest(
        query=body.query,
        mode=body.mode,
        top_k=body.top_k,
        filters=SearchFilters(source_ids=body.source_ids),
    )
    results = await service.search(request, ctx)
    written = await answer_from_hits(body.query, results.hits, container.gateway)
    history.record(container, request, results, ctx, answered=bool(written.text))
    return AnswerResponse(
        query=body.query,
        answer=written.text,
        citations=written.citations,
        model=written.model,
        degraded=written.degraded,
        degraded_reason=written.degraded_reason,
        results=results,
    )
