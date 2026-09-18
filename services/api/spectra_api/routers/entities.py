"""Entity lookup, search and the resolution cascade."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from spectra_schemas import CanonicalEntity, EntityResolution

from ..dependencies import Container, Ctx, service_or_503
from ..errors import NotFound

router = APIRouter(tags=["entities"])


class ResolveRequest(BaseModel):
    surface: str = Field(min_length=1, max_length=512)
    entity_type: str | None = None


class EntityDetail(BaseModel):
    entity: CanonicalEntity
    cross_modal_links: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    application_links: list[dict[str, Any]] = Field(default_factory=list)


@router.get("/entities", response_model=list[CanonicalEntity])
async def search_entities(
    container: Container, ctx: Ctx, q: str = "", type: str | None = None, limit: int = 25
) -> list[CanonicalEntity]:
    service = service_or_503(container, "entities")
    if q:
        return await service.search_entities(q, limit=limit)
    return await container.storage.repository.list_entities(entity_type=type, limit=limit)


@router.post("/entities/resolve", response_model=EntityResolution)
async def resolve_entity(body: ResolveRequest, container: Container, ctx: Ctx) -> EntityResolution:
    service = service_or_503(container, "entities")
    return await service.resolve(body.surface, ctx, entity_type=body.entity_type)


@router.get("/entities/{entity_id}", response_model=EntityDetail)
async def get_entity(entity_id: str, container: Container, ctx: Ctx) -> EntityDetail:
    service = service_or_503(container, "entities")
    entity = await service.get_entity(entity_id)
    if entity is None:
        raise NotFound(f"unknown entity: {entity_id!r}")

    # The service returns {Modality: [EntityLink]}; the wire contract is plain
    # JSON keyed by the modality's value.
    raw_links = await service.cross_modal_links(entity_id)
    links = {
        (key.value if hasattr(key, "value") else str(key)): [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
            for item in items
        ]
        for key, items in raw_links.items()
    }
    app_links: list[dict[str, Any]] = []
    if container.evidence is not None:
        app_links = [link.model_dump() for link in container.evidence.application_links([entity])]
    return EntityDetail(entity=entity, cross_modal_links=links, application_links=app_links)
