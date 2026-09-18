"""SPECTRA Brain - agent controller, tools, hypotheses, disproof and verification.

The controller's own reasoning lives at this level; every specialist agent lives
in its own package under ``agents/``, and the machinery they all share - the tool
contract, the registry, the search gateway - lives under ``tools/``.
"""

from __future__ import annotations

from .agents.disproof import DisproofAgent
from .agents.hypothesis import HypothesisEngine
from .agents.verifier import Verifier
from .autopsy import AutopsyBuilder
from .context import AgentServices, ToolContext
from .explain import ExplanationBuilder
from .gpu import GpuScheduler
from .orchestrator import SpectraBrain
from .persistence import InMemoryStateStore, RepositoryStateStore, StateStore, store_for
from .planner import PlannedCall, initial_plan, replan
from .service import InvestigationService, build_investigation_service, load_peer_services
from .streaming import TraceBroker
from .synthesis import AnswerSynthesiser
from .tools import ToolRegistry, build_registry
from .understanding import QueryUnderstandingService

__all__ = [
    "AgentServices",
    "AnswerSynthesiser",
    "AutopsyBuilder",
    "DisproofAgent",
    "ExplanationBuilder",
    "GpuScheduler",
    "HypothesisEngine",
    "InMemoryStateStore",
    "InvestigationService",
    "PlannedCall",
    "QueryUnderstandingService",
    "RepositoryStateStore",
    "SpectraBrain",
    "StateStore",
    "ToolContext",
    "ToolRegistry",
    "TraceBroker",
    "Verifier",
    "build_investigation_service",
    "build_registry",
    "initial_plan",
    "load_peer_services",
    "replan",
    "store_for",
]
