"""Brain tools: the controller's own reach into the ledger, sources and applications."""

from __future__ import annotations

from typing import Any

from spectra_schemas import (
    AgentName,
    ApplicationLink,
    EntityType,
    EvidenceStance,
    ToolResult,
    ToolSpec,
)

from ...context import ToolContext
from ...evidence_adapter import maybe_await
from ...stance import classify, restance
from ...tools.assets import repository_for
from ...tools.base import Tool
from ...tools.claim_search import search_claim
from ...tools.ledger import select_evidence
from ...tools.payloads import dump, evidence_payload
from ...tools.schemas import (
    DEFAULT_CLAIM_TOP_K,
    EVIDENCE_OUTPUT,
    integer,
    obj,
    string,
    string_array,
)
from ...tools.timeouts import (
    CLAIM_SEARCH_TIMEOUT_SECONDS,
    EVIDENCE_TIMEOUT_SECONDS,
    LOCATOR_TIMEOUT_SECONDS,
)

DEFAULT_EVIDENCE_LIMIT = 12
MAX_EVIDENCE_LIMIT = 50
APPLICATION_TIMEOUT_SECONDS = 10.0

CLAIM_INPUT = obj(
    {
        "claim": string("The statement to test"),
        "top_k": integer("Maximum items per modality", default=DEFAULT_CLAIM_TOP_K, maximum=25),
    },
    required=["claim"],
)


class GetEvidenceTool(Tool):
    spec = ToolSpec(
        name="get_evidence",
        description="Re-read evidence already gathered in this investigation, by id or by weight.",
        agent=AgentName.BRAIN,
        input_schema=obj(
            {
                "evidence_ids": string_array("Specific evidence ids to fetch"),
                "limit": integer("Maximum items", default=DEFAULT_EVIDENCE_LIMIT, maximum=MAX_EVIDENCE_LIMIT),
            }
        ),
        output_schema=EVIDENCE_OUTPUT,
        timeout_seconds=EVIDENCE_TIMEOUT_SECONDS,
        cost_hint=0.1,
    )

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        items = select_evidence(ctx, args.get("evidence_ids"), int(args.get("limit", DEFAULT_EVIDENCE_LIMIT)))
        if not items:
            return self.empty("no evidence has been gathered for this investigation yet")
        return self.success(
            data=evidence_payload(items),
            summary=f"{len(items)} evidence item(s) in the ledger",
            count=len(items),
            evidence_ids=[item.evidence_id for item in items],
        )


class SearchSupportingEvidenceTool(Tool):
    spec = ToolSpec(
        name="search_supporting_evidence",
        description=(
            "Look for evidence that would corroborate a claim across every enabled "
            "modality; returned items carry their stance."
        ),
        agent=AgentName.BRAIN,
        input_schema=CLAIM_INPUT,
        output_schema=EVIDENCE_OUTPUT,
        timeout_seconds=CLAIM_SEARCH_TIMEOUT_SECONDS,
        cost_hint=2.0,
    )

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        claim = args["claim"]
        found = await search_claim(
            ctx, tool=self.spec.name, query=claim, top_k=int(args.get("top_k", DEFAULT_CLAIM_TOP_K))
        )
        items = [restance(item, classify(claim, item)) for item in found]
        supporting = [i for i in items if i.stance is EvidenceStance.SUPPORTING]
        if not items:
            return self.empty(f"no evidence found for: {claim}")
        return self.success(
            data=evidence_payload(items),
            summary=f"{len(supporting)} supporting of {len(items)} retrieved item(s)",
            count=len(items),
            evidence_ids=[item.evidence_id for item in items],
        )


class GetSourceMetadataTool(Tool):
    spec = ToolSpec(
        name="get_source_metadata",
        description="Describe a connected source: type, modalities, health and volume.",
        agent=AgentName.BRAIN,
        input_schema=obj({"source_id": string("Source id")}, required=["source_id"]),
        output_schema=obj({"source": {"type": "object", "description": "Source descriptor without credentials"}}),
        timeout_seconds=LOCATOR_TIMEOUT_SECONDS,
        cost_hint=0.2,
    )

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        repository = await repository_for(ctx, self.spec.name)
        source = await maybe_await(repository.get_source(args["source_id"]))
        if source is None:
            return self.empty(f"no source with id '{args['source_id']}'")
        payload = source.model_dump(mode="json")
        payload.pop("connection", None)  # never surface connection details to the model
        payload.pop("credential_ref", None)
        return self.success(
            data={"source": payload},
            summary=f"{payload.get('name')} ({payload.get('type')}), status {payload.get('status')}",
            count=1,
        )


def _entity_type(value: str | None) -> EntityType:
    if not value:
        return EntityType.OTHER
    try:
        return EntityType(value.strip().lower())
    except ValueError:
        return EntityType.OTHER


class OpenApplicationRecordTool(Tool):
    spec = ToolSpec(
        name="open_application_record",
        description=(
            "Produce the deep link that opens this entity in the enterprise application, "
            "confirming first that the record exists."
        ),
        agent=AgentName.BRAIN,
        input_schema=obj(
            {
                "entity_id": string("Canonical entity id"),
                "entity_type": string("Entity type, e.g. transaction, customer, incident"),
                "record_id": string("Application record id, when it differs from the entity id"),
            },
            required=["entity_id"],
        ),
        output_schema=obj(
            {"links": {"type": "array", "description": "ApplicationLink payloads", "items": {"type": "object"}}}
        ),
        timeout_seconds=APPLICATION_TIMEOUT_SECONDS,
        cost_hint=0.2,
    )

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        links = await self._from_service(ctx, args["entity_id"])
        if not links:
            link = await self._build_link(ctx, args)
            links = [link] if link else []
        if not links:
            return self.empty(f"no application record is registered for {args['entity_id']}")
        return self.success(
            data={"links": dump(links)},
            summary=f"{len(links)} application link(s) for {args['entity_id']}",
            count=len(links),
        )

    async def _from_service(self, ctx: ToolContext, entity_id: str) -> list[ApplicationLink]:
        resolver = getattr(getattr(ctx.services.evidence, "applications", None), "resolve_many", None)
        if resolver is None:
            return []
        resolved = await maybe_await(resolver([entity_id]))
        return [link for link in (resolved or []) if isinstance(link, ApplicationLink)]

    async def _build_link(self, ctx: ToolContext, args: dict[str, Any]) -> ApplicationLink | None:
        entity_type = _entity_type(args.get("entity_type"))
        record_id = args.get("record_id") or args["entity_id"]
        verified = await self._record_exists(ctx, entity_type.value, record_id)
        base = ctx.settings.application_base_url.rstrip("/")
        return ApplicationLink(
            entity_id=args["entity_id"],
            entity_type=entity_type,
            label=f"{entity_type.value.title()} {record_id}",
            url=f"{base}/records/{entity_type.value}/{record_id}",
            record_id=str(record_id),
            verified_in_database=verified,
        )

    async def _record_exists(self, ctx: ToolContext, entity_type: str, record_id: str) -> bool:
        lookup = getattr(ctx.services.sources, "database_lookup", None) if ctx.services.sources else None
        if lookup is None:
            return False
        rows = await maybe_await(lookup(entity_type, record_id))
        if isinstance(rows, dict):
            rows = rows.get("rows") or rows.get("records") or []
        return bool(rows)


BRAIN_TOOLS: tuple[type[Tool], ...] = (
    GetEvidenceTool,
    SearchSupportingEvidenceTool,
    GetSourceMetadataTool,
    OpenApplicationRecordTool,
)
