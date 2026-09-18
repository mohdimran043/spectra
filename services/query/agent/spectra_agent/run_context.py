"""The live handle on one investigation run.

Sub-agents (disproof, verification) need to spend tool-call budget and see the
evidence gathered so far.  They do that through this handle rather than by
reaching into the orchestrator, so every call they make is budgeted, traced and
recorded exactly like a planned one.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from spectra_schemas import InvestigationState, ToolResult

from .context import ToolContext
from .execution import ExecutionEngine
from .planner import PlannedCall


class Run:
    """Mutable holder around the immutable state of one investigation."""

    def __init__(self, state: InvestigationState, ctx: ToolContext, engine: ExecutionEngine) -> None:
        self.state = state
        self.ctx = ctx
        self._engine = engine

    async def batch(self, calls: Sequence[PlannedCall]) -> list[ToolResult]:
        outcome = await self._engine.run(self.state, calls, self.ctx)
        self.state = outcome.state
        return outcome.results

    async def call(self, tool: str, args: dict[str, Any]) -> ToolResult:
        results = await self.batch([PlannedCall(tool, args, f"{tool} requested by the Brain")])
        if results:
            return results[0]
        return ToolResult(
            tool=tool,
            ok=False,
            error=self.state.budget.exhausted_reason or "the call was not attempted",
            summary="not executed",
        )
