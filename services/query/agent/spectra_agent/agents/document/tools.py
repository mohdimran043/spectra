"""Document Agent tools: search the corpus, and open one page of it."""

from __future__ import annotations

from typing import Any

from spectra_schemas import (
    AgentName,
    DocumentLocator,
    EvidenceKind,
    Modality,
    Provenance,
    ToolResult,
    ToolSpec,
)

from ...context import ToolContext
from ...evidence_adapter import maybe_await
from ...tools.assets import asset_for, evidence_for_chunk, locator_value, repository_for
from ...tools.base import Tool
from ...tools.modality_search import ModalitySearchTool
from ...tools.payloads import evidence_payload
from ...tools.schemas import EVIDENCE_OUTPUT, SEARCH_INPUT, integer, obj, string
from ...tools.timeouts import LOCATOR_TIMEOUT_SECONDS, SEARCH_TIMEOUT_SECONDS

DEFAULT_PAGE = 1
MAX_PAGE = 10000


class SearchDocumentsTool(ModalitySearchTool):
    modality = Modality.DOCUMENT
    spec = ToolSpec(
        name="search_documents",
        description=(
            "Hybrid lexical + semantic search across ingested documents "
            "(PDF, Office, email, text). Returns citable evidence with page-level provenance."
        ),
        agent=AgentName.DOCUMENT,
        input_schema=SEARCH_INPUT,
        output_schema=EVIDENCE_OUTPUT,
        timeout_seconds=SEARCH_TIMEOUT_SECONDS,
        requires_flag="document",
        cost_hint=1.0,
    )


class GetDocumentPageTool(Tool):
    spec = ToolSpec(
        name="get_document_page",
        description="Read one page of an ingested document as citable evidence.",
        agent=AgentName.DOCUMENT,
        input_schema=obj(
            {
                "document_id": string("Asset id of the document"),
                "page": integer("Page number, 1-based", default=DEFAULT_PAGE, minimum=1, maximum=MAX_PAGE),
            },
            required=["document_id"],
        ),
        output_schema=EVIDENCE_OUTPUT,
        timeout_seconds=LOCATOR_TIMEOUT_SECONDS,
        requires_flag="document",
        cost_hint=0.3,
    )

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        asset = await asset_for(ctx, self.spec.name, args["document_id"])
        repository = await repository_for(ctx, self.spec.name)
        page = int(args.get("page", DEFAULT_PAGE))
        chunks = list(await maybe_await(repository.list_chunks_by_asset(asset.asset_id)) or [])
        on_page = [c for c in chunks if int(locator_value(c, "page") or 0) == page]
        if not on_page:
            return self.empty(f"page {page} of {asset.title} has no indexed text")
        items = [
            evidence_for_chunk(
                chunk,
                asset,
                Provenance(
                    source_id=chunk.source_id,
                    source_name=None,
                    modality=Modality.DOCUMENT,
                    object_uri=asset.object_uri,
                    locator=DocumentLocator(document_id=asset.asset_id, page=page),
                ),
                EvidenceKind.DOCUMENT,
                self.spec.name,
            )
            for chunk in on_page
        ]
        return self.success(
            data=evidence_payload(items),
            summary=f"page {page} of '{asset.title}' ({len(items)} passage(s))",
            count=len(items),
            evidence_ids=[item.evidence_id for item in items],
        )


DOCUMENT_TOOLS: tuple[type[Tool], ...] = (SearchDocumentsTool, GetDocumentPageTool)
