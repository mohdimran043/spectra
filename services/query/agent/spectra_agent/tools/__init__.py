"""Shared tool infrastructure: the contract every tool call goes through.

The 22 tools themselves no longer live here - each one belongs to an agent and
sits in that agent's package under ``spectra_agent/agents/``.  What stays here
is what no single agent owns: the :class:`Tool` contract (validation, timeout,
GPU serialisation, never-raise), the registry that filters tools by deployment
flags, the reusable JSON-schema fragments, the search gateway, the claim fan-out
and the evidence payload helpers.

``build_registry`` is assembled by ``spectra_agent.agents`` - the agents know
which tools exist, the toolkit does not - and is re-exported here because that
is the import path callers have always used.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .base import Tool, require_service
from .payloads import dump, evidence_payload, pack_evidence, unpack_evidence
from .registry import ALTERNATIVES, ToolRegistry
from .validation import validate_args

if TYPE_CHECKING:  # pragma: no cover - import-cycle-free typing only
    from ..agents import ALL_TOOL_TYPES as ALL_TOOL_TYPES
    from ..agents import build_registry as build_registry

# Resolved lazily: the agent packages import this one, so importing them at
# module level here would close the loop.
_AGENT_EXPORTS = frozenset({"ALL_TOOL_TYPES", "build_registry"})


def __getattr__(name: str) -> Any:
    """Re-export the agent-owned registry builders without an import cycle."""
    if name in _AGENT_EXPORTS:
        from .. import agents

        return getattr(agents, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ALL_TOOL_TYPES",
    "ALTERNATIVES",
    "Tool",
    "ToolRegistry",
    "build_registry",
    "dump",
    "evidence_payload",
    "pack_evidence",
    "require_service",
    "unpack_evidence",
    "validate_args",
]
