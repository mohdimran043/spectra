"""Contradiction Radar tool: find gathered evidence that cannot all be true."""

from __future__ import annotations

from typing import Any

from spectra_schemas import AgentName, ToolResult, ToolSpec

from ...context import ToolContext
from ...evidence_adapter import maybe_await
from ...tools.base import Tool
from ...tools.ledger import select_evidence
from ...tools.payloads import dump
from ...tools.schemas import integer, obj, string_array
from ...tools.timeouts import EVIDENCE_TIMEOUT_SECONDS
from . import contradictions as local_contradictions

DEFAULT_CONTRADICTION_LIMIT = 10
MAX_CONTRADICTION_LIMIT = 50
# The detector compares pairs, so it is fed the heaviest slice of the ledger
# rather than the whole of it.
CANDIDATE_POOL = 50


class DetectContradictionsTool(Tool):
    spec = ToolSpec(
        name="detect_contradictions",
        description="Find pairs of gathered evidence that cannot both be true.",
        agent=AgentName.CONTRADICTION,
        input_schema=obj(
            {
                "evidence_ids": string_array("Restrict the check to these evidence ids"),
                "limit": integer(
                    "Maximum contradictions",
                    default=DEFAULT_CONTRADICTION_LIMIT,
                    maximum=MAX_CONTRADICTION_LIMIT,
                ),
            }
        ),
        output_schema=obj(
            {"contradictions": {"type": "array", "description": "Contradiction payloads", "items": {"type": "object"}}}
        ),
        timeout_seconds=EVIDENCE_TIMEOUT_SECONDS,
        cost_hint=0.5,
    )

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        items = select_evidence(ctx, args.get("evidence_ids"), limit=CANDIDATE_POOL)
        if len(items) < 2:
            return self.empty("at least two evidence items are needed to detect a contradiction")
        # Scope to what this investigation is about: a disagreement elsewhere in
        # the corpus is not this question's business.
        focal = list(ctx.focal_entities)
        limit = int(args.get("limit", DEFAULT_CONTRADICTION_LIMIT))
        found = local_contradictions.detect(items, limit=limit, focal=focal)
        if not found:
            detector = getattr(getattr(ctx.services.evidence, "contradictions", None), "detect", None)
            if detector is not None:
                found = await maybe_await(detector(items))
        if not found:
            return self.empty(f"no contradictions among {len(items)} evidence item(s)")
        return self.success(
            data={"contradictions": dump(found)},
            summary=f"{len(found)} contradiction(s) detected",
            count=len(found),
        )


CONTRADICTION_TOOLS: tuple[type[Tool], ...] = (DetectContradictionsTool,)
