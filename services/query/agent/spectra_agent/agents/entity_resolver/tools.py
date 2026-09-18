"""Entity Resolver tools - surface form to canonical entity, and entity discovery."""

from __future__ import annotations

from typing import Any

from spectra_schemas import AgentName, ToolError, ToolResult, ToolSpec

from ...context import ToolContext
from ...evidence_adapter import maybe_await
from ...tools.base import Tool, require_service
from ...tools.payloads import dump
from ...tools.schemas import integer, obj, string

ENTITY_TIMEOUT_SECONDS = 15.0
DEFAULT_ENTITY_LIMIT = 10
MAX_ENTITY_LIMIT = 50


class ResolveEntityTool(Tool):
    spec = ToolSpec(
        name="resolve_entity",
        description=(
            "Resolve a surface form (an id, a name, a partial reference) to a canonical "
            "entity, with the candidate list and the method that matched."
        ),
        agent=AgentName.ENTITY_RESOLVER,
        input_schema=obj(
            {
                "surface": string("The text to resolve, e.g. an identifier or a name"),
                "entity_type": string("Expected entity type, when known"),
            },
            required=["surface"],
        ),
        output_schema=obj(
            {
                "resolution": {"type": "object", "description": "EntityResolution payload"},
                "entity_id": {"type": "string", "description": "Canonical id when resolved"},
                "confidence": {"type": "number", "description": "Resolution confidence"},
            }
        ),
        timeout_seconds=ENTITY_TIMEOUT_SECONDS,
        requires_flag="entity_resolution",
        cost_hint=0.4,
    )

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        service = require_service(ctx, "entities", self.spec.name)
        resolve = getattr(service, "resolve", None)
        if resolve is None:
            raise ToolError(self.spec.name, "the entity resolution service exposes no resolve()")
        resolution = await maybe_await(resolve(args["surface"], ctx.permissions))
        if resolution is None:
            return self.empty(f"'{args['surface']}' did not resolve to a known entity")
        payload = dump(resolution)
        resolved = payload.get("resolved") if isinstance(payload, dict) else None
        entity_id = (resolved or {}).get("entity_id", "")
        confidence = float((payload or {}).get("confidence", 0.0))
        if not entity_id:
            return self.empty(
                f"'{args['surface']}' matched no canonical entity "
                f"({len((payload or {}).get('candidates', []))} candidate(s) considered)"
            )
        return self.success(
            data={"resolution": payload, "entity_id": entity_id, "confidence": confidence},
            summary=f"'{args['surface']}' resolved to {entity_id} (confidence {confidence:.2f})",
            count=1,
        )


class SearchEntitiesTool(Tool):
    spec = ToolSpec(
        name="search_entities",
        description="Find canonical entities whose name, alias or key matches the given text.",
        agent=AgentName.ENTITY_RESOLVER,
        input_schema=obj(
            {
                "text": string("Text to match against entity names and aliases"),
                "limit": integer("Maximum entities", default=DEFAULT_ENTITY_LIMIT, maximum=MAX_ENTITY_LIMIT),
            },
            required=["text"],
        ),
        output_schema=obj(
            {"entities": {"type": "array", "description": "CanonicalEntity payloads", "items": {"type": "object"}}}
        ),
        timeout_seconds=ENTITY_TIMEOUT_SECONDS,
        requires_flag="entity_resolution",
        cost_hint=0.4,
    )

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        service = require_service(ctx, "entities", self.spec.name)
        search = getattr(service, "search_entities", None)
        if search is None:
            raise ToolError(self.spec.name, "the entity resolution service exposes no search_entities()")
        limit = int(args.get("limit", DEFAULT_ENTITY_LIMIT))
        entities = dump(await maybe_await(search(args["text"])) or [])
        if not entities:
            return self.empty(f"no entity matched '{args['text']}'")
        trimmed = entities[:limit]
        names = ", ".join(str(e.get("canonical_name", e.get("entity_id", "?"))) for e in trimmed[:3])
        return self.success(
            data={"entities": trimmed},
            summary=f"{len(trimmed)} entity match(es): {names}",
            count=len(trimmed),
        )


ENTITY_TOOLS: tuple[type[Tool], ...] = (ResolveEntityTool, SearchEntitiesTool)
