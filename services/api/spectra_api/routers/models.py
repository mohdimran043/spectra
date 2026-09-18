"""Model runtime dashboard endpoints (the GPU / VRAM view)."""

from __future__ import annotations

from fastapi import APIRouter
from spectra_schemas import ModelRole, ModelRuntimeStatus

from ..dependencies import Container, Ctx, CtxManageModels
from ..errors import DependencyUnavailable, NotFound

router = APIRouter(tags=["models"])


@router.get("/models", response_model=ModelRuntimeStatus)
async def model_status(container: Container, ctx: Ctx) -> ModelRuntimeStatus:
    if container.gateway is None:
        raise DependencyUnavailable("model_gateway", "the model gateway failed to initialise")
    return await container.gateway.status()


@router.post("/models/{role}/unload")
async def unload_role(
    role: str,
    container: Container,
    ctx: CtxManageModels,
) -> dict[str, str]:
    if container.gateway is None:
        raise DependencyUnavailable("model_gateway", "the model gateway failed to initialise")
    try:
        model_role = ModelRole(role)
    except ValueError:
        raise NotFound(f"unknown model role: {role!r}")
    await container.gateway.unload_role(model_role)
    return {"status": "unloaded", "role": model_role.value}
