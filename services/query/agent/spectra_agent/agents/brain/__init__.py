"""Brain - the controller's own four tools.

These are not a specialist agent's capabilities; they are what the orchestrator
needs to do its own job, so they are declared under ``AgentName.BRAIN`` and are
never switched off by a deployment flag.  It can re-read the evidence ledger,
corroborate a claim across every enabled modality, describe a connected source,
and produce the deep link that opens an entity in the enterprise application.

The Brain's reasoning itself - phases, planning, execution, synthesis - stays at
the package root, because it orchestrates the agents rather than being one.
"""

from __future__ import annotations

from .tools import (
    BRAIN_TOOLS,
    GetEvidenceTool,
    GetSourceMetadataTool,
    OpenApplicationRecordTool,
    SearchSupportingEvidenceTool,
)

__all__ = [
    "BRAIN_TOOLS",
    "GetEvidenceTool",
    "GetSourceMetadataTool",
    "OpenApplicationRecordTool",
    "SearchSupportingEvidenceTool",
]
