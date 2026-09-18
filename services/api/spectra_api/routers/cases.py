"""Persistent investigation cases: reopen, continue, attach evidence."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from spectra_schemas import InvestigationCase

from ..dependencies import Container, Ctx, CtxInvestigate, service_or_503
from ..errors import NotFound

router = APIRouter(tags=["cases"])


class AttachEvidence(BaseModel):
    asset_id: str
    note: str = ""


@router.get("/cases", response_model=list[InvestigationCase])
async def list_cases(container: Container, ctx: Ctx, limit: int = 50) -> list[InvestigationCase]:
    return await container.storage.repository.list_cases(limit=limit)


@router.get("/cases/{case_id}", response_model=InvestigationCase)
async def get_case(case_id: str, container: Container, ctx: Ctx) -> InvestigationCase:
    case = await container.storage.repository.get_case(case_id)
    if case is None:
        raise NotFound(f"unknown case: {case_id!r}")
    return case


@router.post("/cases/{case_id}/reopen", response_model=InvestigationCase)
async def reopen_case(
    case_id: str, container: Container, ctx: CtxInvestigate
) -> InvestigationCase:
    service = service_or_503(container, "investigations")
    try:
        return await service.reopen_case(case_id)
    except ValueError:
        raise NotFound(f"unknown case: {case_id!r}")


@router.post("/cases/{case_id}/evidence", response_model=InvestigationCase)
async def attach_evidence(
    case_id: str,
    body: AttachEvidence,
    container: Container,
    ctx: CtxInvestigate,
) -> InvestigationCase:
    service = service_or_503(container, "investigations")
    asset = await container.storage.repository.get_asset(body.asset_id)
    if asset is None:
        raise NotFound(f"unknown asset: {body.asset_id!r}")
    if not ctx.may_read_source(asset.source_id, asset.permissions):
        raise NotFound(f"unknown asset: {body.asset_id!r}")

    # Attaching evidence means the case is reconsidered with it, not that a row
    # is appended somewhere - otherwise "add evidence" would change nothing.
    followup = body.note.strip() or f"Reassess this case taking {asset.title} into account."
    try:
        await service.continue_case(case_id, followup, ctx)
    except ValueError:
        raise NotFound(f"unknown case: {case_id!r}")
    case = await service.get_case(case_id)
    if case is None:
        raise NotFound(f"unknown case: {case_id!r}")
    return case
