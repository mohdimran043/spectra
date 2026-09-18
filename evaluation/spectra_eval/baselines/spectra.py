"""Baseline E: the full evidence-grounded investigation."""

from __future__ import annotations

from typing import Any

from spectra_schemas import PermissionContext, SearchMode

from ..datasets.benchmark import BenchmarkQuestion, Target
from .base import Baseline, BaselineResult


class SpectraBaseline(Baseline):
    name = "spectra"
    description = "Evidence-grounded investigation with disproof and verification"
    lacks = ()

    async def answer(self, question: BenchmarkQuestion, ctx: PermissionContext) -> BaselineResult:
        service = self.container.investigations
        if service is None:
            return BaselineResult(question_id=question.id, status="failed",
                                  error="the investigation service is unavailable")
        state = await service.investigate(
            question.question,
            mode=SearchMode.DEEP if question.mode == "deep" else SearchMode.FAST,
            ctx=ctx,
        )
        return result_from_state(question, state, service)


def result_from_state(question: BenchmarkQuestion, state: Any, service: Any) -> BaselineResult:
    """Translate an InvestigationState into the comparable result shape."""
    answer = service.to_answer(state)
    return BaselineResult(
        question_id=question.id,
        answer=answer.answer,
        status=answer.status.value,
        confidence=answer.confidence,
        targets=_targets(answer.evidence),
        entities=_entities(answer.entities),
        evidence_labels=[str(item.get("label", "")) for item in answer.evidence],
        contradictions=len(answer.contradictions),
        claims=len(answer.claims),
        latency_ms=answer.metrics.total_latency_ms,
        tool_calls=answer.metrics.tool_calls,
        model_calls=len(answer.metrics.models_used),
        degraded=answer.degraded,
    )


def _entities(entries: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for entry in entries:
        name = entry.get("canonical_name") or entry.get("record_id") or entry.get("entity_id")
        if name:
            names.append(str(name))
    return names


def _targets(evidence: list[dict[str, Any]]) -> list[Target]:
    """Reconstruct citations from the evidence ledger's provenance."""
    targets: list[Target] = []
    for item in evidence:
        locator = ((item.get("provenance") or {}).get("locator")) or {}
        kind = str(locator.get("kind", "document"))
        if kind == "document":
            targets.append(Target("document", str(locator.get("document_id", "")),
                                  page=_as_int(locator.get("page"))))
        elif kind == "image":
            targets.append(Target("image", str(locator.get("image_id", ""))))
        elif kind == "video":
            targets.append(Target("video", str(locator.get("video_id", "")),
                                  start_seconds=_as_float(locator.get("start_seconds"))))
        elif kind == "audio":
            targets.append(Target("audio", str(locator.get("audio_id", "")),
                                  start_seconds=_as_float(locator.get("start_seconds"))))
        elif kind == "database":
            targets.append(Target("database", str(locator.get("record_id", ""))))
        else:
            targets.append(Target("external", str(locator.get("resource", ""))))
    return [t for t in targets if t.identifier]


def _as_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
