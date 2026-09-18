#!/usr/bin/env python
"""Emit API fixtures from the REAL pydantic models.

The frontend's Zod schemas and the backend's pydantic models are two
descriptions of one contract.  Hand-written fixtures would only prove the Zod
schemas parse whatever someone typed; these are serialised from the actual
models, so the vitest suite fails the moment the two drift apart.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spectra_schemas import (
    AgentStatus,
    AnswerStatus,
    ApplicationLink,
    Asset,
    AssetKind,
    CanonicalEntity,
    Claim,
    ClaimStatus,
    ConfidenceLabel,
    Contradiction,
    DocumentLocator,
    EntityType,
    EvidenceItem,
    EvidenceKind,
    EvidenceStance,
    GPUStatus,
    GraphEdge,
    GraphNode,
    GraphView,
    HealthReport,
    IngestJob,
    InvestigationAnswer,
    InvestigationMetrics,
    JobStatus,
    Modality,
    ModelCandidate,
    ModelInfo,
    ModelRole,
    ModelRuntimeStatus,
    ModelState,
    Provenance,
    QueryExplanation,
    RetrievalStageStat,
    ScoreBreakdown,
    SearchAutopsy,
    SearchHit,
    SearchMode,
    SearchResponse,
    SourceDescriptor,
    SourceHealth,
    SourceStatus,
    SourceType,
    TimelineEvent,
    TraceStatus,
    TraceStep,
    VideoLocator,
)
from spectra_schemas.enums import AgentName

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


def _evidence(index: int, kind: EvidenceKind, modality: Modality, stance: EvidenceStance) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=f"evd_{index}",
        kind=kind,
        modality=modality,
        summary="The authentication service connection pool was exhausted at 10:42.",
        excerpt="...connection pool was exhausted at 10:42, so the charge failed.",
        provenance=_doc_provenance(),
        stance=stance,
        relevance=0.91,
        reliability=0.75,
        reliability_reason="Document, approved version, names TX82931 explicitly, corroborated by 2 sources",
        entities=["ent_transaction_ab12"],
        occurred_at=NOW,
        retrieved_by="search_documents",
    )


def _answer() -> InvestigationAnswer:
    evidence = [
        _evidence(1, EvidenceKind.DATABASE, Modality.DATABASE, EvidenceStance.SUPPORTING),
        _evidence(2, EvidenceKind.DOCUMENT, Modality.DOCUMENT, EvidenceStance.SUPPORTING),
        _evidence(3, EvidenceKind.VIDEO, Modality.VIDEO, EvidenceStance.NEUTRAL),
    ]
    return InvestigationAnswer(
        investigation_id="inv_abc123",
        answer="Transaction TX82931 failed because the authentication service timed out [E1][E2].",
        confidence=0.94,
        confidence_label=ConfidenceLabel.HIGH,
        status=AnswerStatus.SUPPORTED,
        entities=[{"entity_id": "ent_transaction_ab12", "entity_type": "transaction",
                   "canonical_name": "TX82931", "aliases": ["Txn 82931"]}],
        evidence=[{**e.model_dump(mode="json"), "label": f"E{i + 1}", "citation": e.citation(),
                   "weight": e.weight} for i, e in enumerate(evidence)],
        claims=[
            Claim(
                claim_id="C1",
                text="The authentication service timed out, so TX82931 failed.",
                confidence=0.94,
                status=ClaimStatus.SUPPORTED,
                supporting_evidence=["evd_1", "evd_2"],
                contradicting_evidence=[],
                disproof_probe="A successful authentication call for TX82931 inside the failure window.",
                disproof_searched=True,
                verified=True,
                verification_note="Two independent sources; no unresolved contradiction.",
                rationale="The failure_reason field and the post-mortem agree.",
            ),
            Claim(
                claim_id="C2",
                text="No fraud rule fired for TX82931.",
                confidence=0.71,
                status=ClaimStatus.SUPPORTED,
                supporting_evidence=["evd_1"],
                disproof_probe="A fraud-service decision log showing a rule match for TX82931.",
                disproof_searched=True,
                verified=True,
            ),
        ],
        contradictions=[
            Contradiction(
                contradiction_id="con_1",
                statement="INC1829 status is reported as both 'approved' and 'rejected'",
                evidence_a="evd_2", evidence_b="evd_3", kind="value_conflict",
                detail="The superseded draft says rejected; the approved v2 says approved.",
                resolution="Resolved in favour of evd_2: approved beats superseded.",
                resolved_in_favour_of="evd_2", severity=0.7, entity_id="ent_incident_1",
            )
        ],
        timeline=[
            TimelineEvent(event_id="ev_1", occurred_at=NOW, label="Transaction created",
                          modality=Modality.DATABASE, evidence_ids=["evd_1"], precision="exact"),
            TimelineEvent(event_id="ev_2", occurred_at=NOW + timedelta(seconds=6),
                          label="Authentication failed", detail="auth_timeout",
                          modality=Modality.DATABASE, evidence_ids=["evd_1"], precision="exact"),
        ],
        application_links=[
            ApplicationLink(entity_id="ent_transaction_ab12", entity_type=EntityType.TRANSACTION,
                            label="Open Transaction", url="http://localhost:3001/transactions/TX82931",
                            record_id="TX82931", verified_in_database=True)
        ],
        explanation=QueryExplanation(
            reasons=["The query referenced a transaction ID, so Database Search was selected first."],
            sources_selected=["src_enterprise", "src_docs"],
            sources_skipped=[{"source": "src_images", "reason": "vision agent disabled"}],
        ),
        autopsy=SearchAutopsy(
            investigation_id="inv_abc123",
            sources_considered=["src_enterprise", "src_docs", "src_media"],
            candidates_retrieved=184, evidence_used=3, evidence_rejected=29,
            rejection_reasons={"below relevance floor": 24, "permission denied": 5},
            tool_calls=18, tool_breakdown={"search_documents": 6, "query_database": 3},
            contradictions=1, total_latency_ms=8400.0,
            stage_latency_ms={"candidate_generation": 31.2, "rerank": 88.0},
            models_used=["ollama/qwen3:30b-a3b", "transformers/BAAI/bge-m3"],
            claims_made=2, claims_refuted=0, evidence_diversity=0.95,
        ),
        metrics=InvestigationMetrics(
            total_latency_ms=8400.0, tool_calls=18, iterations=3, candidates_retrieved=184,
            evidence_used=3, evidence_rejected=29, contradictions=1,
            claims_made=2, claims_refuted=0,
            models_used=["ollama/qwen3:30b-a3b"],
            sources_considered=["src_enterprise", "src_docs"],
        ),
        followups=["Which other transactions hit the same incident?"],
    )


def _trace_step() -> TraceStep:
    return TraceStep(
        step_id="step_1", investigation_id="inv_abc123", sequence=3,
        agent=AgentName.DATABASE, tool="query_database", status=TraceStatus.OK,
        title="Database Agent", input_summary="transaction TX82931",
        output_summary="1 record found", started_at=NOW, completed_at=NOW,
        latency_ms=12.4, evidence_ids=["evd_1"],
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
    "investigation-answer": _answer(),
    "trace-step": _trace_step(),
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
    "agent-status": [
        AgentStatus(name="image", label="Vision Agent", enabled=False, ready=False,
                    state="disabled", reason="Disabled in the Agent Control Center.",
                    depends_on=["vision", "ocr"], alternatives=["Documents", "Videos", "Database"],
                    tools=["search_images"])
    ],
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
    "graph-view": GraphView(
        nodes=[GraphNode(node_id="ent_transaction_ab12", labels=["Transaction"],
                         properties={"canonical_name": "TX82931"}),
               GraphNode(node_id="evd_1", labels=["Evidence"], properties={"summary": "auth timeout"})],
        edges=[GraphEdge(edge_id="e1", type="REFERS_TO", start="evd_1", end="ent_transaction_ab12")],
    ),
    "canonical-entity": CanonicalEntity(
        entity_id="ent_transaction_ab12", entity_type=EntityType.TRANSACTION,
        canonical_name="TX82931", aliases=["Txn 82931", "Transaction #82931"],
        normalized_keys=["TX82931"], modalities=[Modality.DOCUMENT, Modality.VIDEO], mention_count=7),
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
