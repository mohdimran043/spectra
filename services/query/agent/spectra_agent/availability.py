"""Which agents are switched on, which are ready, and what to use instead.

A disabled agent is excluded from planning, reported with a reason and with the
enabled alternatives, and the investigation continues in a degraded but honest
state - never crashing, never inventing the output the missing agent would have
produced.
"""

from __future__ import annotations

from collections.abc import Mapping

from spectra_schemas import AgentAvailability

from .context import AgentServices
from .tools import ToolRegistry

# flag -> (display name, representative tool, service attribute it needs)
AGENT_PROFILES: dict[str, tuple[str, str | None, str | None]] = {
    "document": ("Document Agent", "search_documents", "search"),
    "image": ("Vision Agent", "search_images", "search"),
    "video": ("Video Agent", "search_videos", "search"),
    "audio": ("Audio Agent", "search_audio", "search"),
    "database": ("Database Agent", "query_database", "sources"),
    "graph": ("Graph Agent", "search_graph", None),
    "entity_resolution": ("Entity Resolver", "resolve_entity", "entities"),
    "claim": ("Claim Builder", None, None),
    "disproof": ("Disproof Agent", "search_disconfirming_evidence", "search"),
    "verifier": ("Verifier", "verify_claim", None),
}

FALLBACK_ALTERNATIVES: dict[str, tuple[str, ...]] = {
    "claim": ("search_supporting_evidence", "search_disconfirming_evidence"),
    "verifier": ("search_supporting_evidence", "search_disconfirming_evidence"),
    "graph": ("search_entities", "search_documents"),
}


def build(
    flags: Mapping[str, bool], registry: ToolRegistry, services: AgentServices
) -> list[AgentAvailability]:
    """Availability report for every agent this deployment knows about."""
    report: list[AgentAvailability] = []
    for flag, (label, tool, requirement) in AGENT_PROFILES.items():
        enabled = bool(flags.get(flag, True))
        missing_service = requirement is not None and getattr(services, requirement, None) is None
        ready = enabled and not missing_service
        report.append(
            AgentAvailability(
                name=label,
                enabled=enabled,
                ready=ready,
                reason=_reason(enabled, missing_service, requirement),
                alternatives=_alternatives(flag, tool, registry, flags),
            )
        )
    return report


def degraded_reasons(report: list[AgentAvailability]) -> list[str]:
    return [
        f"{entry.name} unavailable: {entry.reason}"
        + (f" (use {', '.join(entry.alternatives)})" if entry.alternatives else "")
        for entry in report
        if not entry.ready and entry.reason
    ]


def _reason(enabled: bool, missing_service: bool, requirement: str | None) -> str | None:
    if not enabled:
        return "switched off in this deployment's agent flags"
    if missing_service:
        return f"the {requirement} service is not available in this deployment"
    return None


def _alternatives(
    flag: str, tool: str | None, registry: ToolRegistry, flags: Mapping[str, bool]
) -> list[str]:
    if tool is not None:
        alternatives = registry.alternatives_for(tool, flags)
        if alternatives:
            return alternatives
    enabled = set(registry.available_names(flags))
    return [name for name in FALLBACK_ALTERNATIVES.get(flag, ()) if name in enabled]
