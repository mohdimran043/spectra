"""Investigation and case persistence.

The Brain itself only knows two callables - ``save_state`` and ``load_state``.
This module provides the two implementations the service wires in: an in-memory
store (tests, and deployments without storage) and one backed by the storage
repository.
"""

from __future__ import annotations

from typing import Any, Protocol

from spectra_config.logging import get_logger
from spectra_schemas import InvestigationCase, InvestigationState

log = get_logger(__name__)


class StateStore(Protocol):
    """What the investigation service needs from a persistence layer."""

    async def save(self, state: InvestigationState) -> None: ...

    async def load(self, investigation_id: str) -> InvestigationState | None: ...

    async def list(self, limit: int = 50) -> list[InvestigationState]: ...

    async def save_case(self, case: InvestigationCase) -> None: ...

    async def load_case(self, case_id: str) -> InvestigationCase | None: ...

    async def list_cases(self, limit: int = 50) -> list[InvestigationCase]: ...


class InMemoryStateStore:
    """Process-local store - ordered newest first."""

    def __init__(self) -> None:
        self._states: dict[str, InvestigationState] = {}
        self._cases: dict[str, InvestigationCase] = {}

    async def save(self, state: InvestigationState) -> None:
        self._states[state.investigation_id] = state

    async def load(self, investigation_id: str) -> InvestigationState | None:
        return self._states.get(investigation_id)

    async def list(self, limit: int = 50) -> list[InvestigationState]:
        ordered = sorted(self._states.values(), key=lambda s: s.updated_at, reverse=True)
        return ordered[:limit]

    async def save_case(self, case: InvestigationCase) -> None:
        self._cases[case.case_id] = case

    async def load_case(self, case_id: str) -> InvestigationCase | None:
        return self._cases.get(case_id)

    async def list_cases(self, limit: int = 50) -> list[InvestigationCase]:
        ordered = sorted(self._cases.values(), key=lambda c: c.updated_at, reverse=True)
        return ordered[:limit]


class RepositoryStateStore:
    """Durable store backed by ``spectra_storage``'s repository."""

    def __init__(self, repository: Any) -> None:
        self._repository = repository

    async def save(self, state: InvestigationState) -> None:
        await self._repository.save_investigation(state)

    async def load(self, investigation_id: str) -> InvestigationState | None:
        return await self._repository.get_investigation(investigation_id)

    async def list(self, limit: int = 50) -> list[InvestigationState]:
        return list(await self._repository.list_investigations(limit))

    async def save_case(self, case: InvestigationCase) -> None:
        await self._repository.save_case(case)

    async def load_case(self, case_id: str) -> InvestigationCase | None:
        return await self._repository.get_case(case_id)

    async def list_cases(self, limit: int = 50) -> list[InvestigationCase]:
        return list(await self._repository.list_cases(limit))


def store_for(storage: Any | None) -> StateStore:
    """Repository-backed store when storage is present, in-memory otherwise."""
    repository = getattr(storage, "repository", None) if storage is not None else None
    if repository is None:
        return InMemoryStateStore()
    return RepositoryStateStore(repository)
