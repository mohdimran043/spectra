"""Guided demo mode: six scenarios that run the real pipeline end to end."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from spectra_schemas import SearchMode

from ..background import spawn
from ..dependencies import Container, Ctx, CtxInvestigate, CtxManageSources, service_or_503
from ..errors import NotFound

router = APIRouter(tags=["demo"])


class Scenario(BaseModel):
    id: str
    title: str
    subtitle: str
    narrative: list[str]
    question: str
    mode: SearchMode
    needs_image: bool = False
    expects: list[str]


SCENARIOS: list[Scenario] = [
    Scenario(
        id="image-to-database",
        title="Image → Database",
        subtitle="A screenshot becomes a structured record",
        narrative=[
            "A screenshot is uploaded and ingested: OCR and captioning run on the ingestion path.",
            "Enterprise identifiers found in the image are resolved to canonical entities.",
            "The Database Agent looks the transaction up and returns the real record.",
            "Application deep links are generated from the resolved ids, not hard-coded.",
        ],
        question="What does this screenshot refer to, and what is the record's current state?",
        mode=SearchMode.FAST,
        needs_image=True,
        expects=["ocr", "entity_resolution", "database", "application_links"],
    ),
    Scenario(
        id="text-to-video",
        title="Text → Video",
        subtitle="Find the moment someone said it",
        narrative=[
            "The query is classified as a media-location intent.",
            "Transcript chunks indexed at ingestion time are retrieved - no video is scanned now.",
            "The result carries a precise timestamp the player seeks to.",
        ],
        question="Find where the engineer discusses the authentication problem.",
        mode=SearchMode.FAST,
        expects=["video", "timestamp", "transcript"],
    ),
    Scenario(
        id="database-to-documents",
        title="Database → Documents",
        subtitle="Structured record to unstructured corroboration",
        narrative=[
            "A database record is the starting point.",
            "Its entities are resolved and used to pivot into documents, video and images.",
            "Every returned item cites its exact page or timestamp.",
        ],
        question="Starting from the failed transaction record, what documentation corroborates it?",
        mode=SearchMode.DEEP,
        expects=["database", "document", "cross_modal"],
    ),
    Scenario(
        id="investigation",
        title="Unified Investigation",
        subtitle="Claims built from evidence, then actively challenged",
        narrative=[
            "The Brain plans, retrieves across every enabled modality and resolves entities.",
            "Claims are derived from the retrieved evidence and scored on it.",
            "The Disproof Agent actively searches for evidence that would refute the leading claim.",
            "The Verifier checks the claim, then the answer is assembled with citations.",
        ],
        question="Investigate why the transaction failed and show me the supporting evidence.",
        mode=SearchMode.DEEP,
        expects=["claims", "disproof", "verification", "evidence_graph", "timeline"],
    ),
    Scenario(
        id="contradiction",
        title="Contradiction Radar",
        subtitle="When sources disagree",
        narrative=[
            "Two documents disagree about whether the incident was approved.",
            "The contradiction is surfaced, not hidden.",
            "Version status, recency and source reliability adjudicate it, and the reasoning is shown.",
        ],
        question="The sources disagree about whether the incident was approved. Investigate.",
        mode=SearchMode.DEEP,
        expects=["contradiction", "resolution", "reliability"],
    ),
    Scenario(
        id="timeline",
        title="Temporal Reconstruction",
        subtitle="How the incident unfolded",
        narrative=[
            "Timestamps are normalised from database rows, documents, video offsets and image EXIF.",
            "A single ordered timeline is reconstructed across every modality.",
        ],
        question="How did this incident evolve, and what happened before the failure?",
        mode=SearchMode.DEEP,
        expects=["timeline", "temporal_reasoning"],
    ),
]

SCENARIO_BY_ID = {s.id: s for s in SCENARIOS}


class ScenarioRun(BaseModel):
    investigation_id: str
    stream_url: str
    scenario: Scenario


@router.get("/demo/scenarios", response_model=list[Scenario])
async def list_scenarios(container: Container, ctx: Ctx) -> list[Scenario]:
    return SCENARIOS


@router.post("/demo/run/{scenario_id}", response_model=ScenarioRun)
async def run_scenario(
    scenario_id: str,
    container: Container,
    ctx: CtxInvestigate,
    asset_id: str | None = None,
) -> ScenarioRun:
    scenario = SCENARIO_BY_ID.get(scenario_id)
    if scenario is None:
        raise NotFound(f"unknown scenario: {scenario_id!r}")

    service = service_or_503(container, "investigations")
    state = await service.create(
        question=scenario.question,
        mode=scenario.mode,
        ctx=ctx,
        asset_ids=[asset_id] if asset_id else [],
    )
    spawn(service.run(state.investigation_id, ctx), name=f"demo:{scenario_id}")
    return ScenarioRun(
        investigation_id=state.investigation_id,
        stream_url=f"/api/stream/investigation/{state.investigation_id}",
        scenario=scenario,
    )


@router.post("/demo/seed")
async def seed_demo(
    container: Container, ctx: CtxManageSources
) -> dict[str, Any]:
    """Ingest the synthetic enterprise dataset.  Idempotent - content-addressed dedupe applies."""
    ingestion = service_or_503(container, "ingestion")
    result = await ingestion.seed_demo_dataset()
    return {"status": "seeded", **result}
