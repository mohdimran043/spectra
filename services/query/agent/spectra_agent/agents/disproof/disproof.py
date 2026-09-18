"""The disproof agent - mandatory, and allowed to find nothing.

Confirmation bias is the failure mode of every retrieval agent: ask for
evidence that X, retrieve evidence that X, conclude X.  This agent asks the
opposite question.  It negates the leading explanation, searches for the
competing outcomes, and reports honestly when the attack finds nothing - that
absence is a result, recorded as such, not a failure.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from spectra_config import Settings, get_settings
from spectra_config.logging import get_logger
from spectra_schemas import (
    EvidenceItem,
    EvidenceStance,
    Hypothesis,
    InvestigationState,
    ToolResult,
)

from ...context import ToolContext
from ...stance import classify, restance
from ...thresholds import MAX_NEGATION_QUERIES
from ..hypothesis.causal_lexicon import disproof_queries

log = get_logger(__name__)

ExecuteTool = Callable[[str, dict], Awaitable[ToolResult]]

# Each negation query is a retrieval round; a handful per query keeps the probe
# inside a deep-mode budget while still covering the competing outcomes.
PROBE_TOP_K = 5


class DisproofAgent:
    """Actively attacks a hypothesis with negation queries."""

    def __init__(
        self,
        execute_tool: ExecuteTool | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._execute_tool = execute_tool
        self._settings = settings or get_settings()

    def queries_for(self, hypothesis: Hypothesis) -> list[str]:
        claim = hypothesis.disproof_probe or hypothesis.description
        return disproof_queries(claim, hypothesis.predicted_signals, limit=MAX_NEGATION_QUERIES)

    async def probe(
        self, hypothesis: Hypothesis, state: InvestigationState, ctx: ToolContext
    ) -> list[EvidenceItem]:
        """Retrieve evidence that would refute ``hypothesis``."""
        queries = self.queries_for(hypothesis)
        collected: dict[str, EvidenceItem] = {}
        for item in await self._retrieve(hypothesis, queries, ctx):
            collected.setdefault(item.evidence_id, item)
        tagged = [
            _tag(restance(item, classify(hypothesis.description, item)), hypothesis)
            for item in collected.values()
        ]
        log.info(
            "disproof.probe",
            hypothesis=hypothesis.hypothesis_id,
            queries=len(queries),
            retrieved=len(tagged),
            conflicting=sum(1 for i in tagged if i.stance is EvidenceStance.CONTRADICTING),
            investigation_id=state.investigation_id,
        )
        return tagged

    async def _retrieve(
        self, hypothesis: Hypothesis, queries: list[str], ctx: ToolContext
    ) -> list[EvidenceItem]:
        if self._execute_tool is not None:
            return await self._via_tool(hypothesis)
        return await self._direct(queries, ctx)

    async def _via_tool(self, hypothesis: Hypothesis) -> list[EvidenceItem]:
        from ...tools.payloads import unpack_evidence

        assert self._execute_tool is not None
        result = await self._execute_tool(
            "search_disconfirming_evidence",
            {
                "claim": hypothesis.disproof_probe or hypothesis.description,
                "signals": list(hypothesis.predicted_signals),
                "top_k": PROBE_TOP_K,
            },
        )
        if not result.ok:
            log.info("disproof.tool_unavailable", error=result.error)
            return []
        return unpack_evidence(result)

    async def _direct(self, queries: list[str], ctx: ToolContext) -> list[EvidenceItem]:
        from ...tools.claim_search import search_claim

        items: list[EvidenceItem] = []
        for query in queries:
            items.extend(
                await search_claim(ctx, tool="disproof_agent", query=query, top_k=PROBE_TOP_K)
            )
        return items

    def describe(self, hypothesis: Hypothesis, items: list[EvidenceItem], queries: int) -> str:
        """Trace-ready summary; 'nothing found' is a real outcome."""
        conflicting = [i for i in items if i.stance is EvidenceStance.CONTRADICTING]
        if conflicting:
            return (
                f"{len(conflicting)} conflicting item(s) found against {hypothesis.hypothesis_id} "
                f"across {queries} negation query(ies)"
            )
        return (
            f"No conflicting evidence found against {hypothesis.hypothesis_id} after {queries} "
            f"negation query(ies); {len(items)} related item(s) were neutral"
        )


def _tag(item: EvidenceItem, hypothesis: Hypothesis) -> EvidenceItem:
    linked = list(item.hypothesis_ids)
    if hypothesis.hypothesis_id not in linked:
        linked.append(hypothesis.hypothesis_id)
    return item.model_copy(update={"hypothesis_ids": linked, "retrieved_by": "disproof_agent"})
