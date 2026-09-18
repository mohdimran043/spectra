"""Agent Control Center: status and runtime enable/disable."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from spectra_schemas import AgentStatus

from ..dependencies import Container, Ctx, CtxManageAgents
from ..errors import NotFound

router = APIRouter(tags=["agents"])

# label, what it needs, and what the Brain uses instead when it is off.
AGENT_CATALOG: dict[str, dict[str, object]] = {
    "document": {
        "label": "Document Agent",
        "depends_on": ["embedding", "reranker"],
        "alternatives": ["Database", "Videos", "Images"],
        "tools": ["search_documents", "get_document_page"],
    },
    "image": {
        "label": "Vision Agent",
        "depends_on": ["vision", "mm_embedding", "ocr"],
        "alternatives": ["Documents", "Videos", "Database"],
        "tools": ["search_images", "get_image"],
    },
    "video": {
        "label": "Video Agent",
        "depends_on": ["speech", "vision", "mm_embedding"],
        "alternatives": ["Documents", "Audio", "Database"],
        "tools": ["search_videos", "get_video_timestamp"],
    },
    "audio": {
        "label": "Audio Agent",
        "depends_on": ["speech", "embedding"],
        "alternatives": ["Documents", "Videos"],
        "tools": ["search_audio"],
    },
    "database": {
        "label": "Database Agent",
        "depends_on": [],
        "alternatives": ["Documents", "Videos", "Images"],
        "tools": ["query_database", "get_database_schema", "get_database_record"],
    },
    "graph": {
        "label": "Evidence Graph",
        "depends_on": [],
        "alternatives": ["Entity Resolution"],
        "tools": ["search_graph", "expand_graph"],
    },
    "entity_resolution": {
        "label": "Entity Resolver",
        "depends_on": ["embedding"],
        "alternatives": ["Exact ID matching only"],
        "tools": ["resolve_entity", "search_entities"],
    },
    "claim": {
        "label": "Claim Builder",
        "depends_on": ["deep_brain"],
        "alternatives": ["Direct retrieval answer"],
        "tools": [],
    },
    "disproof": {
        "label": "Disproof Agent",
        "depends_on": ["deep_brain"],
        "alternatives": ["Support-only evidence"],
        "tools": ["search_disconfirming_evidence"],
    },
    "verifier": {
        "label": "Verifier",
        "depends_on": [],
        "alternatives": ["Unverified answer, confidence capped"],
        "tools": ["verify_claim"],
    },
}


class AgentToggle(BaseModel):
    enabled: bool


def _ready(container: Container, name: str, spec: dict[str, object]) -> tuple[bool, str | None]:
    if container.gateway is None:
        return False, "model gateway unavailable"
    missing = [
        dep
        for dep in spec["depends_on"]  # type: ignore[index]
        if not container.gateway.role_available(_role(dep))
    ]
    if missing:
        return False, f"required model roles unavailable: {', '.join(missing)}"
    return True, None


def _role(name: str):
    from spectra_schemas import ModelRole

    return ModelRole(name)


@router.get("/agents/status", response_model=list[AgentStatus])
async def agent_status(container: Container, ctx: Ctx) -> list[AgentStatus]:
    flags = container.agent_flags()
    out: list[AgentStatus] = []
    for name, spec in AGENT_CATALOG.items():
        enabled = flags.get(name, False)
        ready, reason = _ready(container, name, spec) if enabled else (False, None)
        if not enabled:
            reason = "Disabled in the Agent Control Center."
            state = "disabled"
        elif not ready:
            state = "degraded"
        else:
            state = "ready"
        out.append(
            AgentStatus(
                name=name,
                label=str(spec["label"]),
                enabled=enabled,
                ready=bool(enabled and ready),
                state=state,
                reason=reason,
                depends_on=list(spec["depends_on"]),  # type: ignore[arg-type]
                alternatives=list(spec["alternatives"]),  # type: ignore[arg-type]
                tools=list(spec["tools"]),  # type: ignore[arg-type]
            )
        )
    return out


@router.patch("/agents/{name}")
async def toggle_agent(
    name: str,
    body: AgentToggle,
    container: Container,
    ctx: CtxManageAgents,
) -> dict[str, object]:
    try:
        flags = container.set_agent_flag(name, body.enabled)
    except KeyError:
        raise NotFound(f"unknown agent: {name!r}")
    return {"name": name, "enabled": body.enabled, "flags": flags}
