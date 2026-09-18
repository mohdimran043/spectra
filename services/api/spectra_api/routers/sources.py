"""Source registry: CRUD, health and incremental sync."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field
from spectra_schemas import Modality, SourceDescriptor, SourceHealth, SourceType
from spectra_schemas import new_id as _new_id

from ..dependencies import Container, Ctx, CtxManageSources, service_or_503
from ..errors import NotFound, ValidationRejected

router = APIRouter(tags=["sources"])

SECRET_KEY_HINTS = ("password", "secret", "token", "key", "credential")


def new_source_id(name: str) -> str:
    """A readable, unique source id derived from the operator's chosen name."""
    slug = "".join(ch if ch.isalnum() else "_" for ch in name.lower()).strip("_")[:24]
    return f"src_{slug}" if slug else _new_id("src")


class CreateSource(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: SourceType
    connection: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict, description="Stored in the credential store")
    modalities: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=lambda: ["admin", "analyst", "viewer"])


class UpdateSource(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    reliability_override: float | None = None
    reliability_reason: str | None = None
    permissions: list[str] | None = None


def _reject_inline_secrets(connection: dict[str, Any]) -> None:
    leaked = [k for k in connection if any(h in k.lower() for h in SECRET_KEY_HINTS)]
    if leaked:
        raise ValidationRejected(
            f"secrets must be supplied in 'secrets', not 'connection': {', '.join(sorted(leaked))}"
        )


@router.get("/sources", response_model=list[SourceDescriptor])
async def list_sources(container: Container, ctx: Ctx) -> list[SourceDescriptor]:
    sources = await container.storage.repository.list_sources()
    return [s for s in sources if ctx.may_read_source(s.source_id, s.permissions)]


@router.post("/sources", status_code=status.HTTP_201_CREATED, response_model=SourceDescriptor)
async def create_source(
    body: CreateSource, container: Container, ctx: CtxManageSources
) -> SourceDescriptor:
    _reject_inline_secrets(body.connection)
    service = service_or_503(container, "sources")

    descriptor = SourceDescriptor(
        source_id=new_source_id(body.name),
        name=body.name,
        type=body.type,
        connection=dict(body.connection),
        modalities=[Modality(m) for m in body.modalities],
        permissions=list(body.permissions),
    )
    if body.secrets:
        # Secrets never live on the descriptor; they go to the credential store
        # and the descriptor only keeps the reference.
        store = getattr(service, "credentials", None)
        if store is None:
            raise ValidationRejected("this deployment has no credential store configured")
        reference = store.store(descriptor.source_id, dict(body.secrets))
        descriptor = descriptor.model_copy(update={"credential_ref": reference})
    return await service.create_source(descriptor, ctx)


@router.get("/sources/{source_id}", response_model=SourceDescriptor)
async def get_source(source_id: str, container: Container, ctx: Ctx) -> SourceDescriptor:
    source = await container.storage.repository.get_source(source_id)
    if source is None or not ctx.may_read_source(source_id, source.permissions):
        raise NotFound(f"unknown source: {source_id!r}")
    return source


@router.patch("/sources/{source_id}", response_model=SourceDescriptor)
async def update_source(
    source_id: str,
    body: UpdateSource,
    container: Container,
    ctx: CtxManageSources,
) -> SourceDescriptor:
    service = service_or_503(container, "sources")
    try:
        return await service.update_source(source_id, body.model_dump(exclude_none=True), ctx)
    except (KeyError, ValueError):
        raise NotFound(f"unknown source: {source_id!r}")


@router.delete(
    "/sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_source(source_id: str, container: Container, ctx: CtxManageSources) -> Response:
    service = service_or_503(container, "sources")
    deleted = await service.delete_source(source_id, ctx)
    if not deleted:
        raise NotFound(f"unknown source: {source_id!r}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sources/{source_id}/health", response_model=SourceHealth)
async def source_health(source_id: str, container: Container, ctx: Ctx) -> SourceHealth:
    service = service_or_503(container, "sources")
    try:
        return await service.health(source_id, ctx)
    except (KeyError, ValueError):
        raise NotFound(f"unknown source: {source_id!r}")


@router.post("/sources/{source_id}/sync", status_code=status.HTTP_202_ACCEPTED)
async def sync_source(
    source_id: str, container: Container, ctx: CtxManageSources
) -> dict[str, Any]:
    sources = service_or_503(container, "sources")
    ingestion = service_or_503(container, "ingestion")
    try:
        report = await sources.sync(source_id, ingestion.ingest_discovered, ctx=ctx)
    except (KeyError, ValueError):
        raise NotFound(f"unknown source: {source_id!r}")
    return report


@router.get("/sources/{source_id}/schema")
async def source_schema(source_id: str, container: Container, ctx: Ctx) -> dict[str, Any]:
    service = service_or_503(container, "sources")
    connector = await service.connector(source_id, ctx)
    if connector is None:
        raise NotFound(f"unknown source: {source_id!r}")
    if not hasattr(connector, "get_schema"):
        raise ValidationRejected(f"source {source_id!r} is not a structured data source")
    return await connector.get_schema()
