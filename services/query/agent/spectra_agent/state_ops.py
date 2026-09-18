"""Immutable transitions on :class:`InvestigationState`.

Every function here returns a NEW state.  Nothing in the Brain mutates a
pydantic model in place, which is what makes a persisted investigation and a
streamed trace agree with each other.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from spectra_schemas import (
    BudgetState,
    EvidenceItem,
    EvidenceLedger,
    InvestigationState,
    SearchMode,
    ToolInvocation,
    TraceStep,
)

from . import sufficiency
from .agents.hypothesis import focal_terms


def _now() -> datetime:
    return datetime.now(timezone.utc)


def touch(state: InvestigationState, **updates: object) -> InvestigationState:
    """Apply updates and refresh ``updated_at`` - the one mutation entry point."""
    payload = dict(updates)
    payload["updated_at"] = _now()
    return state.model_copy(update=payload)


def budget_from(mode: SearchMode, budget: object) -> BudgetState:
    """Project a :class:`SearchBudget` onto the serialisable ``BudgetState``."""
    return BudgetState(
        mode=mode,
        max_tool_calls=getattr(budget, "max_tool_calls", 30),
        max_latency_seconds=getattr(budget, "max_latency_seconds", 60.0),
        max_iterations=getattr(budget, "max_iterations", 8),
    )


def next_sequence(state: InvestigationState) -> int:
    return len(state.trace) + 1


def with_trace(state: InvestigationState, step: TraceStep) -> InvestigationState:
    return touch(state, trace=[*state.trace, step])


def with_tool_call(state: InvestigationState, invocation: ToolInvocation) -> InvestigationState:
    metrics = state.metrics.model_copy(update={"tool_calls": state.metrics.tool_calls + 1})
    budget = state.budget.model_copy(update={"tool_calls_used": state.budget.tool_calls_used + 1})
    return touch(state, tool_history=[*state.tool_history, invocation], metrics=metrics, budget=budget)


def with_evidence(
    state: InvestigationState, items: Sequence[EvidenceItem]
) -> tuple[InvestigationState, list[EvidenceItem]]:
    """Admit evidence into the ledger, recording rejections with their reasons."""
    if not items:
        return state, []
    ledger = state.evidence
    accepted, rejections = sufficiency.admit(items, ledger.items, focal_terms(state))
    reasons = dict(ledger.rejection_reasons)
    for reason, count in rejections.items():
        reasons[reason] = reasons.get(reason, 0) + count
    merged = ledger.with_items(accepted)
    new_ledger = EvidenceLedger(
        items=merged.items,
        rejected_count=ledger.rejected_count + sum(rejections.values()),
        considered_count=ledger.considered_count + len(list(items)),
        rejection_reasons=reasons,
    )
    entities = list(state.entities)
    for item in accepted:
        for entity in item.entities:
            if entity not in entities:
                entities.append(entity)
    metrics = state.metrics.model_copy(
        update={
            "candidates_retrieved": state.metrics.candidates_retrieved + len(list(items)),
            "evidence_used": len(new_ledger.items),
            "evidence_rejected": new_ledger.rejected_count,
        }
    )
    return touch(state, evidence=new_ledger, entities=entities, metrics=metrics), accepted


def with_sources_considered(state: InvestigationState, sources: Sequence[str]) -> InvestigationState:
    known = list(state.metrics.sources_considered)
    for source in sources:
        if source and source not in known:
            known.append(source)
    return touch(state, metrics=state.metrics.model_copy(update={"sources_considered": known}))


def with_stage_latency(state: InvestigationState, stage: str, latency_ms: float) -> InvestigationState:
    stages = dict(state.metrics.stage_latency_ms)
    stages[stage] = round(stages.get(stage, 0.0) + latency_ms, 3)
    return touch(state, metrics=state.metrics.model_copy(update={"stage_latency_ms": stages}))


def with_iteration(state: InvestigationState, elapsed_seconds: float) -> InvestigationState:
    budget = state.budget.model_copy(
        update={
            "iterations_used": state.budget.iterations_used + 1,
            "elapsed_seconds": round(elapsed_seconds, 3),
        }
    )
    metrics = state.metrics.model_copy(update={"iterations": budget.iterations_used})
    return touch(state, budget=budget, metrics=metrics)


def with_elapsed(state: InvestigationState, elapsed_seconds: float) -> InvestigationState:
    return touch(state, budget=state.budget.model_copy(update={"elapsed_seconds": round(elapsed_seconds, 3)}))


def exhausted(state: InvestigationState, reason: str) -> InvestigationState:
    if state.budget.exhausted_reason:
        return state
    return touch(state, budget=state.budget.model_copy(update={"exhausted_reason": reason}))


def degraded(state: InvestigationState, reason: str) -> InvestigationState:
    if reason in state.degraded_reasons:
        return state
    return touch(state, degraded=True, degraded_reasons=[*state.degraded_reasons, reason])


def with_plan(state: InvestigationState, entries: Sequence[str]) -> InvestigationState:
    return touch(state, plan=[*state.plan, *[e for e in entries if e not in state.plan]])


def with_updated_evidence(
    state: InvestigationState, items: Sequence[EvidenceItem]
) -> InvestigationState:
    """Merge stance / hypothesis-link updates for evidence already in the ledger."""
    if not items:
        return state
    replacements = {item.evidence_id: item for item in items}
    merged = [replacements.pop(item.evidence_id, item) for item in state.evidence.items]
    extra = [item for item in items if item.evidence_id in replacements]
    ledger = state.evidence.model_copy(update={"items": [*merged, *extra]})
    return touch(state, evidence=ledger)
