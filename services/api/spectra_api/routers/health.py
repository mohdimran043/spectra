"""Health and metrics endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from spectra_schemas import HealthReport

from ..container import _describe_backends
from ..dependencies import Container
from ..metrics import METRICS

router = APIRouter(tags=["system"])

API_VERSION = "1.0.0"


@router.get("/health", response_model=HealthReport)
async def health(container: Container) -> HealthReport:
    components = await container.storage.health()
    components["backends"] = _describe_backends(container.settings)

    if container.gateway is not None:
        status = await container.gateway.status()
        components["models"] = {
            "status": "degraded" if status.degraded else "ok",
            "profile": status.profile,
            "gpu_available": status.gpu.available,
            "detail": "; ".join(status.degraded_reasons) or None,
            "resident_roles": [r.value for r in status.resident_roles],
        }
    else:
        components["models"] = {"status": "error", "detail": "model gateway unavailable"}

    for name in ("search", "entities", "evidence", "ingestion", "investigations", "sources"):
        components[name] = {"status": "ok" if getattr(container, name) is not None else "error"}

    unhealthy = [k for k, v in components.items() if isinstance(v, dict) and v.get("status") == "error"]
    degraded = bool(container.degraded) or any(
        isinstance(v, dict) and v.get("status") == "degraded" for v in components.values()
    )
    overall = "error" if unhealthy else ("degraded" if degraded else "ok")

    return HealthReport(
        status=overall,
        version=API_VERSION,
        deployment_mode=container.settings.deployment_mode.value,
        components=components,
        degraded=degraded or bool(unhealthy),
    )


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    """Process liveness only - never touches a dependency."""
    return {"status": "alive"}


@router.get("/metrics")
async def metrics(request: Request, container: Container) -> Response:
    if container.gateway is not None:
        status = await container.gateway.status()
        METRICS.gauge("gpu_used_mb", status.gpu.used_mb)
        METRICS.gauge("gpu_free_mb", status.gpu.free_mb)
        METRICS.gauge("gpu_total_mb", status.gpu.total_mb)
        for info in status.models:
            METRICS.gauge(f"model_calls{{role={info.role.value}}}", info.call_count)
            METRICS.gauge(f"model_errors{{role={info.role.value}}}", info.error_count)

    stats = await container.storage.repository.stats()
    for key, value in stats.items():
        METRICS.gauge(f"catalog_{key}", value)

    if "text/plain" in (request.headers.get("accept") or ""):
        return Response(METRICS.prometheus(), media_type="text/plain; version=0.0.4")
    return Response(
        content=__import__("json").dumps({**METRICS.snapshot(), "catalog": stats}),
        media_type="application/json",
    )
