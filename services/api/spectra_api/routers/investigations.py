"""Investigation lifecycle: start, read, continue, trace, autopsy, graph, export."""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field
from spectra_config.logging import get_logger
from spectra_schemas import (
    AnswerStatus,
    GraphView,
    InvestigationAnswer,
    InvestigationState,
    InvestigationStatus,
    SearchAutopsy,
    SearchMode,
    TraceStep,
)
from spectra_schemas import investigation_id as new_investigation_id

from ..background import spawn
from ..dependencies import Container, Ctx, CtxInvestigate, service_or_503
from ..errors import ConflictingState, NotFound, ValidationRejected
from ..reporting import render_markdown

log = get_logger(__name__)

router = APIRouter(tags=["investigations"])

MAX_QUESTION_CHARS = 4000


class StartInvestigation(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    mode: SearchMode = SearchMode.DEEP
    asset_ids: list[str] = Field(default_factory=list)
    case_id: str | None = None
    stream: bool = True


class ContinueInvestigation(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    stream: bool = True


class InvestigationAccepted(BaseModel):
    investigation_id: str
    case_id: str | None
    status: str
    stream_url: str


class InvestigationSummary(BaseModel):
    investigation_id: str
    case_id: str | None
    goal: str
    mode: SearchMode
    status: str
    confidence: float
    evidence_count: int
    created_at: str
    updated_at: str


def _check_mode(container: Container, mode: SearchMode) -> None:
    settings = container.settings
    if mode is SearchMode.FAST and not settings.fast_mode_enabled:
        raise ConflictingState("fast mode is disabled by configuration")
    if mode is SearchMode.DEEP and not settings.deep_mode_enabled:
        raise ConflictingState("deep mode is disabled by configuration")


@router.post("/investigations", status_code=status.HTTP_202_ACCEPTED, response_model=InvestigationAccepted)
async def start_investigation(
    body: StartInvestigation,
    response: Response,
    container: Container,
    ctx: CtxInvestigate,
) -> InvestigationAccepted:
    service = service_or_503(container, "investigations")
    _check_mode(container, body.mode)
    question = body.question.strip()

    # Persist a running placeholder first, so the client can attach to the
    # stream (and GET the investigation) before the Brain has produced anything.
    investigation_id = new_investigation_id()
    placeholder = InvestigationState(
        investigation_id=investigation_id,
        case_id=body.case_id,
        goal=question,
        mode=body.mode,
        status=InvestigationStatus.RUNNING,
        uploaded_asset_ids=list(body.asset_ids),
        user_id=ctx.user_id,
        role=ctx.role.value,
    )
    await container.storage.repository.save_investigation(placeholder)

    spawn(
        _run_investigation(
            service=service,
            container=container,
            question=question,
            mode=body.mode,
            ctx=ctx,
            asset_ids=body.asset_ids,
            investigation_id=investigation_id,
            case_id=body.case_id,
        ),
        name=f"investigate:{investigation_id}",
    )
    response.headers["X-Investigation-ID"] = investigation_id
    return InvestigationAccepted(
        investigation_id=investigation_id,
        case_id=body.case_id,
        status=InvestigationStatus.RUNNING.value,
        stream_url=f"/api/stream/investigation/{investigation_id}",
    )


async def _run_investigation(
    *,
    service,
    container,
    question: str,
    mode: SearchMode,
    ctx,
    asset_ids: list[str],
    investigation_id: str,
    case_id: str | None,
) -> None:
    """Drive the Brain and make sure a failure is recorded, never swallowed."""
    try:
        await service.investigate(
            question,
            mode=mode,
            ctx=ctx,
            uploaded_asset_ids=asset_ids,
            investigation_id=investigation_id,
            case_id=case_id,
        )
    except Exception as exc:
        log.error("investigation.failed", investigation_id=investigation_id, error=str(exc), exc_info=True)
        current = await container.storage.repository.get_investigation(investigation_id)
        if current is not None:
            await container.storage.repository.save_investigation(
                current.model_copy(
                    update={
                        "status": InvestigationStatus.FAILED,
                        "answer_status": AnswerStatus.FAILED,
                        "degraded": True,
                        "degraded_reasons": [*current.degraded_reasons, f"investigation failed: {exc}"],
                    }
                )
            )


@router.get("/investigations", response_model=list[InvestigationSummary])
async def list_investigations(container: Container, ctx: Ctx, limit: int = 25) -> list[InvestigationSummary]:
    states = await container.storage.repository.list_investigations(limit=limit)
    return [
        InvestigationSummary(
            investigation_id=s.investigation_id,
            case_id=s.case_id,
            goal=s.goal,
            mode=s.mode,
            status=s.status.value,
            confidence=s.confidence,
            evidence_count=len(s.evidence.items),
            created_at=s.created_at.isoformat(),
            updated_at=s.updated_at.isoformat(),
        )
        for s in states
    ]


async def _state_or_404(container: Container, investigation_id: str):
    state = await container.storage.repository.get_investigation(investigation_id)
    if state is None:
        raise NotFound(f"unknown investigation: {investigation_id!r}")
    return state


@router.get("/investigations/{investigation_id}", response_model=InvestigationAnswer)
async def get_investigation(investigation_id: str, container: Container, ctx: Ctx) -> InvestigationAnswer:
    service = service_or_503(container, "investigations")
    state = await _state_or_404(container, investigation_id)
    return service.to_answer(state)


@router.post("/investigations/{investigation_id}/continue", status_code=status.HTTP_202_ACCEPTED)
async def continue_investigation(
    investigation_id: str,
    body: ContinueInvestigation,
    container: Container,
    ctx: CtxInvestigate,
) -> InvestigationAccepted:
    service = service_or_503(container, "investigations")
    state = await _state_or_404(container, investigation_id)
    if state.status.value == "running":
        raise ConflictingState("this investigation is still running")

    spawn(
        service.continue_investigation(investigation_id, body.question.strip(), ctx),
        name=f"continue:{investigation_id}",
    )
    return InvestigationAccepted(
        investigation_id=investigation_id,
        case_id=state.case_id,
        status="running",
        stream_url=f"/api/stream/investigation/{investigation_id}",
    )


@router.get("/investigations/{investigation_id}/trace", response_model=list[TraceStep])
async def get_trace(investigation_id: str, container: Container, ctx: Ctx) -> list[TraceStep]:
    await _state_or_404(container, investigation_id)
    return await container.storage.repository.get_trace(investigation_id)


@router.get("/investigations/{investigation_id}/autopsy", response_model=SearchAutopsy)
async def get_autopsy(investigation_id: str, container: Container, ctx: Ctx) -> SearchAutopsy:
    if not ctx.can("view_autopsy"):
        raise ValidationRejected("this role may not view the search autopsy")
    service = service_or_503(container, "investigations")
    state = await _state_or_404(container, investigation_id)
    autopsy = service.to_answer(state).autopsy
    if autopsy is None:
        raise NotFound("this investigation has not produced an autopsy yet")
    return autopsy


@router.get("/investigations/{investigation_id}/graph", response_model=GraphView)
async def get_graph(investigation_id: str, container: Container, ctx: Ctx, depth: int = 2) -> GraphView:
    await _state_or_404(container, investigation_id)
    evidence = service_or_503(container, "evidence")
    return await evidence.investigation_graph(investigation_id, depth=depth)


@router.get("/investigations/{investigation_id}/export")
async def export_investigation(
    investigation_id: str, container: Container, ctx: Ctx, format: str = "json"
) -> Response:
    service = service_or_503(container, "investigations")
    state = await _state_or_404(container, investigation_id)
    if format == "markdown":
        body = render_markdown(service.to_answer(state))
        return Response(
            body,
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{investigation_id}.md"'},
        )
    if format != "json":
        raise ValidationRejected("format must be 'json' or 'markdown'")
    answer = service.to_answer(state)
    return Response(
        answer.model_dump_json(indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{investigation_id}.json"'},
    )
