"""The disproof agent - mandatory, and allowed to find nothing.

Confirmation bias is the failure mode of every retrieval agent: ask for evidence
that X, retrieve evidence that X, conclude X.  This agent asks the opposite
question.  It takes the leading claim, negates it, searches for the competing
outcomes, and reports honestly when the attack finds nothing - that absence is a
result, recorded as such, not a failure.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from spectra_config import Settings, get_settings
from spectra_config.logging import get_logger
from spectra_schemas import (
    Claim,
    EvidenceItem,
    EvidenceStance,
    InvestigationState,
    ToolResult,
)

from ...causal_lexicon import disproof_queries
from ...context import ToolContext
from ...stance import classify, restance
from ...thresholds import MAX_NEGATION_QUERIES

log = get_logger(__name__)

ExecuteTool = Callable[[str, dict], Awaitable[ToolResult]]

# Each negation query is a retrieval round; a handful per query keeps the probe
# inside a deep-mode budget while still covering the competing outcomes.
PROBE_TOP_K = 5


class DisproofAgent:
    """Actively attacks a claim with negation queries."""

    def __init__(
        self,
        execute_tool: ExecuteTool | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._execute_tool = execute_tool
        self._settings = settings or get_settings()

    def queries_for(self, claim: Claim) -> list[str]:
        """The searches whose *hits* would weaken ``claim``."""
        return disproof_queries(self._attack_text(claim), limit=MAX_NEGATION_QUERIES)

    async def probe(
        self, claim: Claim, state: InvestigationState, ctx: ToolContext
    ) -> list[EvidenceItem]:
        """Retrieve the evidence that would refute ``claim``."""
        queries = self.queries_for(claim)
        collected: dict[str, EvidenceItem] = {}
        for item in await self._retrieve(claim, queries, ctx):
            collected.setdefault(item.evidence_id, item)
        tagged = [
            _tag(restance(item, classify(claim.text, item)), claim) for item in collected.values()
        ]
        log.info(
            "disproof.probe",
            claim=claim.claim_id,
            queries=len(queries),
            retrieved=len(tagged),
            conflicting=sum(1 for i in tagged if i.stance is EvidenceStance.CONTRADICTING),
            investigation_id=state.investigation_id,
        )
        return tagged

    def describe(self, claim: Claim, items: list[EvidenceItem], queries: int) -> str:
        """Trace-ready summary; 'nothing found' is a real outcome."""
        conflicting = [i for i in items if i.stance is EvidenceStance.CONTRADICTING]
        if conflicting:
            return (
                f"{len(conflicting)} conflicting item(s) found against {claim.claim_id} "
                f"across {queries} negation query(ies)"
            )
        return (
            f"No conflicting evidence found against {claim.claim_id} after {queries} "
            f"negation query(ies); {len(items)} related item(s) were neutral"
        )

    # -- retrieval --------------------------------------------------------
    async def _retrieve(
        self, claim: Claim, queries: list[str], ctx: ToolContext
    ) -> list[EvidenceItem]:
        if self._execute_tool is not None:
            return await self._via_tool(claim)
        return await self._direct(queries, ctx)

    async def _via_tool(self, claim: Claim) -> list[EvidenceItem]:
        from ...tools.payloads import unpack_evidence

        assert self._execute_tool is not None
        result = await self._execute_tool(
            "search_disconfirming_evidence",
            {"claim": self._attack_text(claim), "top_k": PROBE_TOP_K},
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

    def _attack_text(self, claim: Claim) -> str:
        """What the probe is aimed at: the stated probe, else the claim itself."""
        return claim.disproof_probe or claim.text


def _tag(item: EvidenceItem, claim: Claim) -> EvidenceItem:
    linked = list(item.claim_ids)
    if claim.claim_id not in linked:
        linked.append(claim.claim_id)
    return item.model_copy(update={"claim_ids": linked, "retrieved_by": "disproof_agent"})
