"""The SPECTRA agents - one package each, assembled into one tool registry.

Every folder here is an agent: what it does is in its ``__init__`` docstring,
the capabilities it exposes to the Brain are in its ``tools.py``, and the
reasoning it owns (where it has any) sits beside them.  Nothing in here is
wired together directly - agents meet only through the registry below and
through the evidence ledger they all write to.

``build_registry`` holds every tool; the deployment's agent flags decide at call
time which of them are actually offered, so a switched-off agent is invisible to
the planner rather than a runtime failure.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..tools.base import Tool
from ..tools.registry import ToolRegistry
from .audio import AUDIO_TOOLS
from .brain import BRAIN_TOOLS
from .contradiction import CONTRADICTION_TOOLS
from .database import DATABASE_TOOLS
from .disproof import DISPROOF_TOOLS
from .document import DOCUMENT_TOOLS
from .entity_resolver import ENTITY_TOOLS
from .graph import GRAPH_TOOLS
from .timeline import TIMELINE_TOOLS
from .verifier import VERIFIER_TOOLS
from .video import VIDEO_TOOLS
from .vision import VISION_TOOLS

# Retrieval agents first, then the structured-source agents, then the ones that
# reason over what has already been gathered, and the Brain's own tools last -
# the order the planner sees them declared in.
ALL_TOOL_TYPES: tuple[type[Tool], ...] = (
    *DOCUMENT_TOOLS,
    *VISION_TOOLS,
    *VIDEO_TOOLS,
    *AUDIO_TOOLS,
    *DATABASE_TOOLS,
    *GRAPH_TOOLS,
    *ENTITY_TOOLS,
    *DISPROOF_TOOLS,
    *VERIFIER_TOOLS,
    *TIMELINE_TOOLS,
    *CONTRADICTION_TOOLS,
    *BRAIN_TOOLS,
)


def build_registry(flags: Mapping[str, bool] | None = None) -> ToolRegistry:
    """A registry holding every tool, filtered at call time by ``flags``."""
    registry = ToolRegistry(flags)
    registry.register_all([tool_type() for tool_type in ALL_TOOL_TYPES])
    return registry


__all__ = [
    "ALL_TOOL_TYPES",
    "AUDIO_TOOLS",
    "BRAIN_TOOLS",
    "CONTRADICTION_TOOLS",
    "DATABASE_TOOLS",
    "DISPROOF_TOOLS",
    "DOCUMENT_TOOLS",
    "ENTITY_TOOLS",
    "GRAPH_TOOLS",
    "TIMELINE_TOOLS",
    "VERIFIER_TOOLS",
    "VIDEO_TOOLS",
    "VISION_TOOLS",
    "build_registry",
]
