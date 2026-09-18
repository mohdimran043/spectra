"""Verifier tool: hold a claim up against the evidence already gathered."""

from __future__ import annotations

from typing import Any

from spectra_schemas import AgentName, ToolResult, ToolSpec

from ...context import ToolContext
from ...tools.base import Tool
from ...tools.schemas import obj, string, string_array
from ...tools.timeouts import EVIDENCE_TIMEOUT_SECONDS
from .verifier import Verifier


class VerifyClaimTool(Tool):
    spec = ToolSpec(
        name="verify_claim",
        description=(
            "Check a claim against the gathered evidence: entity presence, independent "
            "source count, counter-evidence and evidence diversity."
        ),
        agent=AgentName.VERIFIER,
        input_schema=obj(
            {
                "claim": string("The statement to verify"),
                "evidence_ids": string_array("Restrict verification to these evidence ids"),
            },
            required=["claim"],
        ),
        output_schema=obj({"verification": {"type": "object", "description": "VerificationResult payload"}}),
        timeout_seconds=EVIDENCE_TIMEOUT_SECONDS,
        requires_flag="verifier",
        cost_hint=1.0,
    )

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        ledger = ctx.ledger()
        ids = args.get("evidence_ids")
        if ids:
            wanted = set(ids)
            ledger = ledger.model_copy(
                update={"items": [i for i in ledger.items if i.evidence_id in wanted]}
            )
        verifier = Verifier(settings=ctx.settings, gateway=ctx.services.gateway)
        result = await verifier.verify(args["claim"], ledger, ctx)
        return self.success(
            data={"verification": result.model_dump(mode="json")},
            summary=f"verification {'passed' if result.supported else 'failed'}: {result.note}",
            count=len(result.supporting_evidence),
            evidence_ids=list(result.supporting_evidence),
        )


VERIFIER_TOOLS: tuple[type[Tool], ...] = (VerifyClaimTool,)
