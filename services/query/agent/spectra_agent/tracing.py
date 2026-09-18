"""Trace emission: the only channel through which the Brain narrates itself.

Steps carry action summaries - what was called, what came back, which evidence
it produced.  Model reasoning never enters a trace.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from spectra_config.logging import get_logger
from spectra_schemas import AgentName, InvestigationState, TraceStatus, TraceStep, new_id

from . import state_ops
from .streaming import TraceBroker

log = get_logger(__name__)

OnTrace = Callable[[TraceStep], Awaitable[None]]


class Tracer:
    """Appends a step to the state and publishes it to every listener."""

    def __init__(self, broker: TraceBroker | None = None, on_trace: OnTrace | None = None) -> None:
        self._broker = broker
        self._on_trace = on_trace

    async def emit(self, step: TraceStep) -> None:
        if self._broker is not None:
            await self._broker.publish(step)
        if self._on_trace is None:
            return
        try:
            await self._on_trace(step)
        except Exception as exc:  # a broken consumer must never stop the agent
            log.warning("trace.callback_failed", error=str(exc))

    async def step(
        self,
        state: InvestigationState,
        agent: AgentName,
        *,
        title: str,
        output_summary: str = "",
        input_summary: str = "",
        status: TraceStatus = TraceStatus.OK,
        evidence_ids: Sequence[str] = (),
    ) -> InvestigationState:
        step = TraceStep(
            step_id=new_id("step"),
            investigation_id=state.investigation_id,
            sequence=state_ops.next_sequence(state),
            agent=agent,
            status=status,
            title=title,
            input_summary=input_summary,
            output_summary=output_summary,
            evidence_ids=list(evidence_ids),
        )
        state = state_ops.with_trace(state, step)
        await self.emit(step)
        return state

    async def close(self, investigation_id: str) -> None:
        if self._broker is not None:
            await self._broker.close(investigation_id)
