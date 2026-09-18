"""Execution context handed to every tool.

The Brain never reaches for a global: the services it consumes, the permission
context it must honour and the live budget all arrive through this object, and
every derived context is a *new* frozen instance.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from spectra_config import Settings, get_settings
from spectra_schemas import (
    BudgetState,
    Contradiction,
    EvidenceLedger,
    PermissionContext,
    SearchMode,
)

if TYPE_CHECKING:  # pragma: no cover - imports only for type checkers
    from spectra_ai_core.gateway import ModelGateway


@dataclass(frozen=True)
class AgentServices:
    """The peer services the Brain consumes, injected rather than imported.

    Any member may be ``None``: the corresponding tools then report a precise
    "service unavailable" error instead of inventing a result.
    """

    search: Any | None = None
    entities: Any | None = None
    evidence: Any | None = None
    sources: Any | None = None
    storage: Any | None = None
    gateway: ModelGateway | None = None

    def missing(self) -> list[str]:
        return [name for name in ("search", "entities", "evidence", "sources") if getattr(self, name) is None]


def _empty_ledger() -> EvidenceLedger:
    return EvidenceLedger()


def _no_contradictions() -> list[Contradiction]:
    return []


@dataclass(frozen=True)
class ToolContext:
    """Everything a tool is allowed to know about the run it serves."""

    investigation_id: str
    permissions: PermissionContext
    services: AgentServices
    budget: BudgetState
    settings: Settings = field(default_factory=get_settings)
    mode: SearchMode = SearchMode.DEEP
    goal: str = ""
    uploaded_asset_ids: tuple[str, ...] = ()
    ledger_provider: Callable[[], EvidenceLedger] = _empty_ledger
    contradiction_provider: Callable[[], list[Contradiction]] = _no_contradictions
    agent_flags: dict[str, bool] = field(default_factory=dict)

    def with_budget(self, budget: BudgetState) -> ToolContext:
        return replace(self, budget=budget)

    def with_snapshot(self, state: Any) -> ToolContext:
        """Bind this context to one immutable investigation snapshot."""
        return replace(
            self,
            ledger_provider=lambda: state.evidence,
            contradiction_provider=lambda: list(state.contradictions),
        )

    def ledger(self) -> EvidenceLedger:
        try:
            return self.ledger_provider()
        except Exception:  # pragma: no cover - a broken provider must not kill a tool
            return EvidenceLedger()

    def contradictions(self) -> list[Contradiction]:
        try:
            return list(self.contradiction_provider())
        except Exception:  # pragma: no cover - a broken provider must not kill a tool
            return []

    def flag_enabled(self, flag: str | None) -> bool:
        if not flag:
            return True
        return bool(self.agent_flags.get(flag, True))
