"""Disproof Agent tool: go looking for the evidence that would refute a claim."""

from __future__ import annotations

from typing import Any

from spectra_schemas import AgentName, EvidenceItem, EvidenceStance, ToolResult, ToolSpec

from ...causal_lexicon import disproof_queries
from ...context import ToolContext
from ...stance import classify, restance
from ...thresholds import MAX_NEGATION_QUERIES
from ...tools.base import Tool
from ...tools.claim_search import search_claim
from ...tools.payloads import evidence_payload
from ...tools.schemas import DEFAULT_CLAIM_TOP_K, EVIDENCE_OUTPUT, integer, obj, string, string_array
from ...tools.timeouts import CLAIM_SEARCH_TIMEOUT_SECONDS


class SearchDisconfirmingEvidenceTool(Tool):
    spec = ToolSpec(
        name="search_disconfirming_evidence",
        description=(
            "Actively look for evidence that would REFUTE a claim: the negated claim and "
            "its competing outcomes. Finding nothing is itself a reportable result."
        ),
        agent=AgentName.DISPROOF,
        input_schema=obj(
            {
                "claim": string("The statement to attack"),
                "signals": string_array("Predicted signals whose absence would weaken the claim"),
                "top_k": integer("Maximum items per query", default=DEFAULT_CLAIM_TOP_K, maximum=25),
            },
            required=["claim"],
        ),
        output_schema=EVIDENCE_OUTPUT,
        timeout_seconds=CLAIM_SEARCH_TIMEOUT_SECONDS,
        requires_flag="disproof",
        cost_hint=3.0,
    )

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        claim = args["claim"]
        queries = disproof_queries(claim, args.get("signals") or (), limit=MAX_NEGATION_QUERIES)
        collected: dict[str, EvidenceItem] = {}
        for query in queries:
            for item in await search_claim(
                ctx, tool=self.spec.name, query=query, top_k=int(args.get("top_k", DEFAULT_CLAIM_TOP_K))
            ):
                collected.setdefault(item.evidence_id, item)
        items = [restance(item, classify(claim, item)) for item in collected.values()]
        conflicting = [i for i in items if i.stance is EvidenceStance.CONTRADICTING]
        if not conflicting:
            return self.success(
                data=evidence_payload(items) | {"queries": queries, "conflicting": 0},
                summary=(
                    f"no conflicting evidence found for '{claim}' after {len(queries)} "
                    f"negation query(ies); {len(items)} related item(s) were neutral"
                ),
                count=len(items),
                evidence_ids=[item.evidence_id for item in items],
            )
        return self.success(
            data=evidence_payload(items) | {"queries": queries, "conflicting": len(conflicting)},
            summary=f"{len(conflicting)} conflicting item(s) found across {len(queries)} negation query(ies)",
            count=len(items),
            evidence_ids=[item.evidence_id for item in items],
        )


DISPROOF_TOOLS: tuple[type[Tool], ...] = (SearchDisconfirmingEvidenceTool,)
