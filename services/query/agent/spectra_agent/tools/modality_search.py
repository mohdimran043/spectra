"""The shared body behind the four modality search tools.

``search_documents``, ``search_images``, ``search_videos`` and ``search_audio``
belong to four different agents but ask the search service the same question,
so the question is asked in exactly one place and each agent contributes only
its own ``ToolSpec``.
"""

from __future__ import annotations

from typing import Any

from spectra_schemas import Modality, ToolResult

from ..context import ToolContext
from ..evidence_adapter import evidence_from_hits
from .base import Tool
from .payloads import evidence_payload
from .search_gateway import build_request, run_search


class ModalitySearchTool(Tool):
    """Shared body for the four modality search tools."""

    modality: Modality

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        request = build_request(
            query=args["query"],
            modality=self.modality,
            top_k=int(args.get("top_k", 10)),
            mode=ctx.mode,
            source_ids=args.get("source_ids") or (),
        )
        response = await run_search(
            ctx,
            tool=self.spec.name,
            request=request,
            modality=self.modality,
            image_asset_id=args.get("image_asset_id"),
        )
        items = await evidence_from_hits(
            response.hits, retrieved_by=self.spec.name, services=ctx.services.evidence
        )
        degraded_reason = "; ".join(response.degraded_reasons) or None
        if not items:
            return self.empty(
                f"no {self.modality.value} evidence matched '{request.query}' "
                f"({response.total_candidates} candidates screened)"
            )
        return self.success(
            data=evidence_payload(items),
            summary=(
                f"{len(items)} {self.modality.value} item(s) from "
                f"{len({i.provenance.source_id for i in items})} source(s)"
            ),
            count=len(items),
            evidence_ids=[item.evidence_id for item in items],
            degraded=response.degraded,
            degraded_reason=degraded_reason,
        )
