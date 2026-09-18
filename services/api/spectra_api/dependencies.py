"""FastAPI dependencies: the service container and the permission context.

The auth shim is deliberately thin.  Every retrieval path already takes a
``PermissionContext``, so replacing these headers with OAuth/OIDC/Keycloak is a
change to this file alone.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header
from spectra_config import get_settings
from spectra_schemas import PermissionContext, Role

from .container import ServiceContainer, get_container
from .errors import DependencyUnavailable, PermissionDenied

USER_HEADER = "X-Spectra-User"
ROLE_HEADER = "X-Spectra-Role"


async def container_dep() -> ServiceContainer:
    return await get_container()


Container = Annotated[ServiceContainer, Depends(container_dep)]


async def permission_context(
    x_spectra_user: Annotated[str | None, Header(alias=USER_HEADER)] = None,
    x_spectra_role: Annotated[str | None, Header(alias=ROLE_HEADER)] = None,
) -> PermissionContext:
    settings = get_settings()
    role_value = (x_spectra_role or settings.default_role.value).strip().lower()
    try:
        role = Role(role_value)
    except ValueError:
        raise PermissionDenied(f"unknown role: {role_value!r}")
    return PermissionContext(user_id=(x_spectra_user or "local-user").strip(), role=role)


Ctx = Annotated[PermissionContext, Depends(permission_context)]


def require(capability: str):
    """Dependency factory enforcing a capability from the role model."""

    async def _check(ctx: Ctx) -> PermissionContext:
        if not ctx.can(capability):
            raise PermissionDenied(f"role '{ctx.role.value}' may not {capability}")
        return ctx

    return _check


# Capability-scoped context types.  Declared as aliases rather than as parameter
# defaults because FastAPI forbids `Depends` in both `Annotated` and a default.
CtxUpload = Annotated[PermissionContext, Depends(require("upload"))]
CtxManageSources = Annotated[PermissionContext, Depends(require("manage_sources"))]
CtxManageModels = Annotated[PermissionContext, Depends(require("manage_models"))]


def service_or_503(container: ServiceContainer, name: str):
    """Fetch a service, converting absence into an honest 503."""
    service = getattr(container, name, None)
    if service is None:
        reasons = [r for r in container.degraded if name.split("_")[0] in r] or container.degraded
        raise DependencyUnavailable(name, reasons[0] if reasons else f"{name} is not available")
    return service
