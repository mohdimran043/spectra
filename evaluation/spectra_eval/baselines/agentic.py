"""Baseline D: tool-using retrieval, WITHOUT claim grounding, disproof or verification.

This is the interesting control. It gets the same tools and the same iterative
loop as SPECTRA, so the D -> E comparison isolates exactly what the
claim builder, the disproof agent and the verifier contribute - separately
from the contribution of merely being agentic.
"""

from __future__ import annotations

from spectra_config import get_settings
from spectra_schemas import PermissionContext, SearchMode

from ..datasets.benchmark import BenchmarkQuestion
from .base import Baseline, BaselineResult
from .spectra import result_from_state

# The flags that make SPECTRA more than an agentic retriever.
DISABLED_FOR_AGENTIC = ("claim", "disproof", "verifier")


class AgenticBaseline(Baseline):
    name = "agentic"
    description = "Tool-using iterative retrieval with no claim grounding or challenge"
    lacks = ("claim grounding", "disconfirming search", "verification")

    async def answer(self, question: BenchmarkQuestion, ctx: PermissionContext) -> BaselineResult:
        service = self.container.investigations
        if service is None:
            return BaselineResult(question_id=question.id, status="failed",
                                  error="the investigation service is unavailable")

        # Turn off the three differentiating components for the duration of this
        # question, then restore exactly what was there before.
        previous = dict(self.container.agent_overrides)
        self.container.agent_overrides = {
            **previous,
            **{flag: False for flag in DISABLED_FOR_AGENTIC},
        }
        try:
            state = await service.investigate(
                question.question,
                mode=SearchMode.DEEP if question.mode == "deep" else SearchMode.FAST,
                ctx=ctx,
            )
        finally:
            self.container.agent_overrides = previous

        result = result_from_state(question, state, service)
        result.claims = 0  # by construction
        return result


def settings_snapshot() -> dict[str, bool]:
    """The configured flags, for the report's provenance section."""
    return dict(get_settings().agent_flags())
