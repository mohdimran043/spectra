"""Executing planned tool calls: parallel where independent, budgeted, traced.

Independent retrieval runs concurrently through ``asyncio.gather``; GPU-heavy
tools still serialise behind the single GPU slot inside ``Tool.run``.  Budget is
checked *before* each call, and a call that cannot be afforded is not attempted:
the run stops cleanly with a reason instead of overrunning.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from time import perf_counter

from spectra_config.logging import get_logger
from spectra_schemas import (
    AgentName,
    EvidenceItem,
    InvestigationState,
    ToolInvocation,
    ToolResult,
    TraceStatus,
    TraceStep,
    call_id,
    new_id,
)

from . import state_ops
from .context import ToolContext
from .planner import PlannedCall
from .tools import ToolRegistry, unpack_evidence

log = get_logger(__name__)

TraceEmitter = Callable[[TraceStep], Awaitable[None]]


@dataclass
class ExecutionOutcome:
    """What one batch of tool calls produced."""

    state: InvestigationState
    results: list[ToolResult] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    stopped_reason: str | None = None


class ExecutionEngine:
    """Runs planned calls against the registry, keeping state and trace in step."""

    def __init__(self, registry: ToolRegistry, emit: TraceEmitter) -> None:
        self._registry = registry
        self._emit = emit
        self._agents: dict[str, AgentName] = {}

    async def run(
        self,
        state: InvestigationState,
        calls: Sequence[PlannedCall],
        ctx: ToolContext,
    ) -> ExecutionOutcome:
        affordable, stopped = self._affordable(state, calls)
        if stopped:
            state = state_ops.exhausted(state, stopped)
        if not affordable:
            return ExecutionOutcome(state=state, stopped_reason=stopped)

        snapshot = state
        call_ctx = ctx.with_budget(state.budget).with_snapshot(snapshot)
        started = {call.key(): await self._start_step(state, call) for call in affordable}
        results = await asyncio.gather(
            *(self._invoke(call, call_ctx) for call in affordable), return_exceptions=False
        )

        admitted: list[EvidenceItem] = []
        for call, (result, latency_ms) in zip(affordable, results, strict=True):
            state, new_items = await self._absorb(state, call, result, latency_ms, started[call.key()])
            admitted.extend(new_items)
        return ExecutionOutcome(state=state, results=[r for r, _ in results], evidence=admitted)

    # -- internals --------------------------------------------------------
    def _affordable(
        self, state: InvestigationState, calls: Sequence[PlannedCall]
    ) -> tuple[list[PlannedCall], str | None]:
        remaining = state.budget.tool_calls_remaining
        if remaining <= 0:
            return [], (
                f"tool-call budget exhausted ({state.budget.tool_calls_used}/"
                f"{state.budget.max_tool_calls} calls used)"
            )
        if len(calls) <= remaining:
            return list(calls), None
        return list(calls[:remaining]), (
            f"tool-call budget exhausted ({state.budget.max_tool_calls} calls); "
            f"{len(calls) - remaining} planned call(s) were not attempted"
        )

    async def _invoke(self, call: PlannedCall, ctx: ToolContext) -> tuple[ToolResult, float]:
        started = perf_counter()
        result = await self._registry.call(call.tool, call.args, ctx)
        return result, round((perf_counter() - started) * 1000, 3)

    async def _start_step(self, state: InvestigationState, call: PlannedCall) -> str:
        identifier = new_id("step")
        await self._emit(
            TraceStep(
                step_id=identifier,
                investigation_id=state.investigation_id,
                sequence=state_ops.next_sequence(state),
                agent=self._agent_for(call.tool),
                tool=call.tool,
                status=TraceStatus.STARTED,
                title=f"Calling {call.tool}",
                input_summary=call.reason,
            )
        )
        return identifier

    async def _absorb(
        self,
        state: InvestigationState,
        call: PlannedCall,
        result: ToolResult,
        latency_ms: float,
        identifier: str,
    ) -> tuple[InvestigationState, list[EvidenceItem]]:
        invocation = ToolInvocation(
            call_id=call_id(),
            tool=call.tool,
            arguments=dict(call.args),
            latency_ms=latency_ms,
            ok=result.ok,
            error=result.error,
            result_summary=result.summary,
            result_count=result.count,
        )
        state = state_ops.with_tool_call(state, invocation)
        state = state_ops.with_plan(state, [call.describe()])
        state = state_ops.with_stage_latency(state, f"tool.{call.tool}", latency_ms)

        items = unpack_evidence(result)
        state, admitted = state_ops.with_evidence(state, items)
        if admitted:
            state = state_ops.with_sources_considered(
                state, [item.provenance.source_id for item in admitted]
            )
        if result.degraded and result.degraded_reason:
            state = state_ops.degraded(state, result.degraded_reason)

        step = TraceStep(
            step_id=identifier,
            investigation_id=state.investigation_id,
            sequence=state_ops.next_sequence(state),
            agent=self._agent_for(call.tool),
            tool=call.tool,
            status=_status_of(result),
            title=f"{call.tool} finished",
            input_summary=call.reason,
            output_summary=result.summary or result.error or "",
            latency_ms=latency_ms,
            evidence_ids=[item.evidence_id for item in admitted],
            error=result.error,
            metadata={"accepted": len(admitted), "returned": len(items)},
        )
        state = state_ops.with_trace(state, step)
        await self._emit(step)
        return state, admitted

    def _agent_for(self, tool: str) -> AgentName:
        if tool not in self._agents:
            registered = self._registry.get(tool)
            self._agents[tool] = registered.spec.agent if registered else AgentName.BRAIN
        return self._agents[tool]


def _status_of(result: ToolResult) -> TraceStatus:
    if not result.ok:
        return TraceStatus.ERROR
    if result.degraded:
        return TraceStatus.DEGRADED
    return TraceStatus.OK if result.count else TraceStatus.EMPTY
