"""Evidence-graph traversal."""

from __future__ import annotations

from fastapi import APIRouter
from spectra_schemas import GraphView

from ..dependencies import Container, Ctx, service_or_503
from ..errors import NotFound, ValidationRejected

router = APIRouter(tags=["graph"])

MAX_DEPTH = 4


@router.get("/graph/{node_id}", response_model=GraphView)
async def get_subgraph(
    node_id: str, container: Container, ctx: Ctx, depth: int = 2, types: str | None = None
) -> GraphView:
    if not 1 <= depth <= MAX_DEPTH:
        raise ValidationRejected(f"depth must be between 1 and {MAX_DEPTH}")
    service = service_or_503(container, "evidence")
    edge_types = [t.strip() for t in types.split(",")] if types else None
    view = await service.graph.subgraph(node_id, depth, edge_types=edge_types)
    if not view.nodes:
        raise NotFound(f"unknown graph node: {node_id!r}")
    return view


@router.get("/graph")
async def graph_stats(container: Container, ctx: Ctx) -> dict[str, int]:
    return await container.storage.graph.counts()
