"""Graph Agent tools - find a subgraph for a query, and expand a node's neighbourhood."""

from __future__ import annotations

from typing import Any

from spectra_schemas import AgentName, ToolError, ToolResult, ToolSpec

from ...context import ToolContext
from ...evidence_adapter import maybe_await
from ...tools.base import Tool
from ...tools.payloads import dump
from ...tools.schemas import integer, obj, string, string_array

GRAPH_TIMEOUT_SECONDS = 20.0
DEFAULT_GRAPH_LIMIT = 50
MAX_GRAPH_LIMIT = 200
# Two hops reaches "the entities my entity touches, and what they touch"; three
# hops on an enterprise graph returns most of the graph and explains nothing.
DEFAULT_DEPTH = 1
MAX_DEPTH = 3
# Expanding more than five seed entities returns a hairball rather than an answer.
MAX_SEED_ENTITIES = 5

GRAPH_OUTPUT = obj(
    {
        "nodes": {"type": "array", "description": "Graph nodes", "items": {"type": "object"}},
        "edges": {"type": "array", "description": "Graph edges", "items": {"type": "object"}},
        "entity_ids": string_array("Entity ids represented in the subgraph"),
    }
)


def _as_graph(payload: Any) -> dict[str, list[dict[str, Any]]]:
    """Normalise GraphView / dict / neighbour payloads to nodes+edges."""
    data = dump(payload) or {}
    if isinstance(data, list):
        return {"nodes": [n for n in data if isinstance(n, dict)], "edges": []}
    nodes = data.get("nodes") or []
    edges = data.get("edges") or data.get("relationships") or []
    return {
        "nodes": [n for n in nodes if isinstance(n, dict)],
        "edges": [e for e in edges if isinstance(e, dict)],
    }


def _entity_ids(graph: dict[str, list[dict[str, Any]]]) -> list[str]:
    ids: list[str] = []
    for node in graph["nodes"]:
        node_id = str(node.get("node_id") or node.get("id") or "")
        if node_id and node_id not in ids:
            ids.append(node_id)
    return ids


class SearchGraphTool(Tool):
    spec = ToolSpec(
        name="search_graph",
        description=(
            "Find the entity subgraph relevant to a query: which entities are involved "
            "and how they are connected across sources and modalities."
        ),
        agent=AgentName.GRAPH,
        input_schema=obj(
            {
                "query": string("Text naming the entities of interest"),
                "limit": integer("Maximum nodes", default=DEFAULT_GRAPH_LIMIT, maximum=MAX_GRAPH_LIMIT),
            },
            required=["query"],
        ),
        output_schema=GRAPH_OUTPUT,
        timeout_seconds=GRAPH_TIMEOUT_SECONDS,
        requires_flag="graph",
        cost_hint=0.8,
    )

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        entity_ids = await self._entities_for(ctx, args["query"])
        if not entity_ids:
            return self.empty(f"no graph entity matched '{args['query']}'")
        graph = await self._subgraph(ctx, entity_ids, int(args.get("limit", DEFAULT_GRAPH_LIMIT)))
        graph_ids = _entity_ids(graph) or entity_ids
        return self.success(
            data={"nodes": graph["nodes"], "edges": graph["edges"], "entity_ids": graph_ids},
            summary=f"{len(graph['nodes'])} node(s) and {len(graph['edges'])} edge(s) around {len(entity_ids)} entity(ies)",
            count=len(graph["nodes"]),
        )

    async def _entities_for(self, ctx: ToolContext, query: str) -> list[str]:
        entities = getattr(ctx.services, "entities", None)
        search = getattr(entities, "search_entities", None) if entities else None
        if search is None:
            return []
        found = dump(await maybe_await(search(query)) or [])
        return [str(e.get("entity_id")) for e in found if isinstance(e, dict) and e.get("entity_id")]

    async def _subgraph(self, ctx: ToolContext, entity_ids: list[str], limit: int) -> dict[str, list[dict[str, Any]]]:
        evidence = getattr(ctx.services, "evidence", None)
        subgraph = getattr(getattr(evidence, "graph", None), "subgraph", None)
        if subgraph is not None:
            return _as_graph(await maybe_await(subgraph(entity_ids)))
        storage = getattr(ctx.services, "storage", None)
        neighbours = getattr(getattr(storage, "graph", None), "neighbours", None)
        entities = getattr(ctx.services, "entities", None)
        cross_modal = getattr(entities, "cross_modal_links", None) if entities else None
        if neighbours is None and cross_modal is None:
            raise ToolError(self.spec.name, "no graph backend is available")
        merged: dict[str, list[dict[str, Any]]] = {"nodes": [], "edges": []}
        for entity_id in entity_ids[:MAX_SEED_ENTITIES]:
            payload = (
                await maybe_await(neighbours(entity_id, DEFAULT_DEPTH, None, limit))
                if neighbours is not None
                else await maybe_await(cross_modal(entity_id))
            )
            part = _as_graph(payload)
            merged["nodes"].extend(part["nodes"])
            merged["edges"].extend(part["edges"])
        return merged


class ExpandGraphTool(Tool):
    spec = ToolSpec(
        name="expand_graph",
        description=(
            "Expand one entity's neighbourhood - the records, documents and media it is "
            "linked to - to a bounded depth."
        ),
        agent=AgentName.GRAPH,
        input_schema=obj(
            {
                "node_id": string("Entity or node id to expand"),
                "depth": integer("Hops to expand", default=DEFAULT_DEPTH, minimum=1, maximum=MAX_DEPTH),
                "limit": integer("Maximum nodes", default=DEFAULT_GRAPH_LIMIT, maximum=MAX_GRAPH_LIMIT),
                "edge_types": string_array("Restrict to these relationship types"),
            },
            required=["node_id"],
        ),
        output_schema=GRAPH_OUTPUT,
        timeout_seconds=GRAPH_TIMEOUT_SECONDS,
        requires_flag="graph",
        cost_hint=0.8,
    )

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        node_id = args["node_id"]
        depth = int(args.get("depth", DEFAULT_DEPTH))
        limit = int(args.get("limit", DEFAULT_GRAPH_LIMIT))
        graph = await self._expand(ctx, node_id, depth, limit, args.get("edge_types") or None)
        if not graph["nodes"] and not graph["edges"]:
            return self.empty(f"{node_id} has no recorded links")
        return self.success(
            data={"nodes": graph["nodes"], "edges": graph["edges"], "entity_ids": _entity_ids(graph)},
            summary=f"{len(graph['nodes'])} neighbour(s) of {node_id} at depth {depth}",
            count=len(graph["nodes"]),
        )

    async def _expand(
        self, ctx: ToolContext, node_id: str, depth: int, limit: int, edge_types: list[str] | None
    ) -> dict[str, list[dict[str, Any]]]:
        evidence = getattr(ctx.services, "evidence", None)
        subgraph = getattr(getattr(evidence, "graph", None), "subgraph", None)
        if subgraph is not None:
            return _as_graph(await maybe_await(subgraph([node_id])))
        entities = getattr(ctx.services, "entities", None)
        cross_modal = getattr(entities, "cross_modal_links", None) if entities else None
        if cross_modal is not None:
            return _as_graph(await maybe_await(cross_modal(node_id)))
        storage = getattr(ctx.services, "storage", None)
        neighbours = getattr(getattr(storage, "graph", None), "neighbours", None)
        if neighbours is None:
            raise ToolError(self.spec.name, "no graph backend is available")
        return _as_graph(await maybe_await(neighbours(node_id, depth, edge_types, limit)))


GRAPH_TOOLS: tuple[type[Tool], ...] = (SearchGraphTool, ExpandGraphTool)
