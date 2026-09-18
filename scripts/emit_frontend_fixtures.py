#!/usr/bin/env python
"""Emit API fixtures from the REAL pydantic models.

The frontend's Zod schemas and the backend's pydantic models are two
descriptions of one contract.  Hand-written fixtures would only prove the Zod
schemas parse whatever someone typed; these are serialised from the actual
models, so the vitest suite fails the moment the two drift apart.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from spectra_schemas import (
    Asset,
    AssetKind,
    DocumentLocator,
    GPUStatus,
    HealthReport,
    IngestJob,
    JobStatus,
    Modality,
    ModelCandidate,
    ModelInfo,
    ModelRole,
    ModelRuntimeStatus,
    ModelState,
    Provenance,
    RetrievalStageStat,
    ScoreBreakdown,
    SearchHit,
    SearchMode,
    SearchResponse,
    SourceDescriptor,
    SourceHealth,
    SourceStatus,
    SourceType,
    VideoLocator,
)

OUT = Path(__file__).resolve().parents[1] / "apps/frontend/src/lib/__fixtures__"
NOW = datetime(2026, 3, 11, 10, 42, 1, tzinfo=timezone.utc)
SHA = "ab" + "c" * 62
URI = f"spectra://objects/ab/{SHA}.pdf"


def _doc_provenance() -> Provenance:
    return Provenance(
        source_id="src_docs",
        source_name="Corporate Documents",
        modality=Modality.DOCUMENT,
        object_uri=URI,
        locator=DocumentLocator(document_id="DOC9182", page=14, section="Authentication"),
        content_hash=SHA,
        version="2",
        version_status="approved",
        created_at=NOW,
        ingested_at=NOW,
        index_version="idx_0001",
    )


def _search_response() -> SearchResponse:
    return SearchResponse(
        query="authentication failures",
        mode=SearchMode.FAST,
        total_candidates=184,
        latency_ms=142.3,
        entities=["ent_transaction_ab12"],
        stages=[
            RetrievalStageStat(stage="candidate_generation", candidates_out=184, latency_ms=31.2),
            RetrievalStageStat(stage="filtering", candidates_in=184, candidates_out=97, latency_ms=1.1),
            RetrievalStageStat(stage="rerank", candidates_in=97, candidates_out=12, latency_ms=88.0),
        ],
        hits=[
            SearchHit(
                chunk_id="chk_1",
                asset_id="ast_1",
                source_id="src_docs",
                modality=Modality.DOCUMENT,
                title="Incident_Report.pdf",
                snippet="the «authentication» service timed out",
                score=0.87,
                scores=ScoreBreakdown(
                    lexical=0.7, semantic=0.8, rerank=0.9, entity_match=1.0,
                    metadata_match=0.2, source_reliability=0.75, freshness=0.6, final=0.87,
                ),
                provenance=_doc_provenance(),
                entities=["ent_transaction_ab12"],
                occurred_at=NOW,
            ),
            SearchHit(
                chunk_id="chk_2",
                asset_id="ast_2",
                source_id="src_media",
                modality=Modality.VIDEO,
                title="engineering-standup.mp4",
                snippet="the auth service was «unavailable»",
                score=0.61,
                provenance=Provenance(
                    source_id="src_media",
                    modality=Modality.VIDEO,
                    object_uri=f"spectra://objects/ab/{SHA}.mp4",
                    locator=VideoLocator(
                        video_id="VID129", scene_id="s3", start_seconds=2537.0, end_seconds=2581.0
                    ),
                ),
            ),
        ],
    )


def _model_status() -> ModelRuntimeStatus:
    return ModelRuntimeStatus(
        profile="rtx4090",
        gpu=GPUStatus(available=False, budget_mb=22000.0,
                      detail="nvidia-smi: Driver/library version mismatch"),
        models=[
            ModelInfo(
                role=ModelRole.DEEP_BRAIN, purpose="Planning and synthesis",
                state=ModelState.LOADED, active_runtime="ollama", active_model="qwen3:30b-a3b",
                device="cpu", call_count=12, total_latency_ms=240000.0,
                candidates=[ModelCandidate(runtime="ollama", model="qwen3:30b-a3b",
                                           vram_mb=19000, device="auto", available=True)],
            )
        ],
        resident_roles=[ModelRole.DEEP_BRAIN], degraded=True,
        degraded_reasons=["gpu: driver/library version mismatch"],
    )


FIXTURES = {
    "search-response": _search_response(),
    "model-runtime-status": _model_status(),
    "health-report": HealthReport(
        status="degraded",
        degraded=True,
        components={
            # A healthy component reports no detail at all - the schema must
            # accept that rather than demanding a string.
            "vectors": {"backend": "embedded", "status": "ok", "detail": None},
            "models": {"status": "degraded", "detail": "no GPU"},
        },
        backends={"relational": "sqlite", "vector": "embedded"},
    ),
    "source-descriptor": [
        SourceDescriptor(source_id="src_docs", name="Corporate Documents", type=SourceType.S3,
                         modalities=[Modality.DOCUMENT], status=SourceStatus.HEALTHY,
                         asset_count=412, record_count=0)
    ],
    "source-health": SourceHealth(source_id="src_docs", status=SourceStatus.HEALTHY,
                                  latency_ms=12.0, asset_count=412),
    "asset": Asset(asset_id="ast_1", source_id="src_docs", kind=AssetKind.DOCUMENT,
                   title="Incident_Report.pdf", object_uri=URI, media_type="application/pdf",
                   size_bytes=182_331, content_hash=SHA, status=JobStatus.READY, page_count=14),
    "ingest-job": IngestJob(job_id="job_1", asset_id="ast_1", source_id="src_uploads",
                            status=JobStatus.EMBEDDING, stage="embedding", progress=0.6,
                            stages_completed=["queued", "processing", "extracting"]),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, value in FIXTURES.items():
        if isinstance(value, list):
            payload = [v.model_dump(mode="json") for v in value]
        else:
            payload = value.model_dump(mode="json")
        path = OUT / f"{name}.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        print(f"  wrote {path.relative_to(OUT.parents[4])}")
    print(f"\n{len(FIXTURES)} fixtures emitted from the live pydantic models")


if __name__ == "__main__":
    main()
