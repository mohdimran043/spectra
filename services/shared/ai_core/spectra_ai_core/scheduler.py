"""Sequential GPU scheduling: one lock, a VRAM budget and least-recently-used eviction.

The rtx4090 profile sets ``allow_concurrent_gpu_models: false``, which this module
reads as *at most one heavyweight cuda-resident role at a time*; small helpers
(an embedder, a reranker) may stay co-resident while the budget allows.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, replace

from spectra_config.logging import get_logger
from spectra_schemas import ModelRole

from .registry import ProfileSpec

log = get_logger(__name__)

# A role needing at least this much VRAM counts as "heavyweight" and, under a
# no-concurrency profile, may not share the card with another heavyweight role.
HEAVYWEIGHT_VRAM_MB = 4096


@dataclass(frozen=True)
class Resident:
    """One cuda-resident role and when it was last touched."""

    role: ModelRole
    vram_mb: int
    last_used: float

    @property
    def is_heavyweight(self) -> bool:
        return self.vram_mb >= HEAVYWEIGHT_VRAM_MB


@dataclass(frozen=True)
class AdmissionPlan:
    """What must be evicted before a role can be admitted, or why it cannot be."""

    evict: tuple[ModelRole, ...] = ()
    refusal: str = ""

    @property
    def is_admissible(self) -> bool:
        return not self.refusal


class GpuScheduler:
    """VRAM accounting plus the single lock that serialises loads and evictions."""

    def __init__(self, profile: ProfileSpec, budget_mb: int | None = None) -> None:
        self.profile = profile
        self.budget_mb = int(budget_mb if budget_mb is not None else profile.vram_budget_mb)
        self.lock = asyncio.Lock()
        self._resident: dict[ModelRole, Resident] = {}
        self._waiting = 0

    # -- introspection ----------------------------------------------------
    @property
    def used_mb(self) -> int:
        return sum(entry.vram_mb for entry in self._resident.values())

    @property
    def free_mb(self) -> int:
        return max(0, self.budget_mb - self.used_mb)

    @property
    def queue_depth(self) -> int:
        return self._waiting

    def resident_roles(self) -> list[ModelRole]:
        ordered = sorted(self._resident.values(), key=lambda entry: entry.last_used, reverse=True)
        return [entry.role for entry in ordered]

    def is_resident(self, role: ModelRole) -> bool:
        return role in self._resident

    # -- mutation ---------------------------------------------------------
    def touch(self, role: ModelRole) -> None:
        entry = self._resident.get(role)
        if entry is not None:
            self._resident[role] = replace(entry, last_used=time.monotonic())

    def admit(self, role: ModelRole, vram_mb: int) -> None:
        self._resident[role] = Resident(role=role, vram_mb=vram_mb, last_used=time.monotonic())

    def release(self, role: ModelRole) -> None:
        self._resident.pop(role, None)

    def idle_roles(self, idle_seconds: float, busy: frozenset[ModelRole]) -> list[ModelRole]:
        cutoff = time.monotonic() - idle_seconds
        return [
            entry.role
            for entry in self._resident.values()
            if entry.last_used < cutoff and entry.role not in busy
        ]

    # -- admission --------------------------------------------------------
    def plan(self, role: ModelRole, vram_mb: int, busy: frozenset[ModelRole] = frozenset()) -> AdmissionPlan:
        """Decide which residents to evict so ``role`` fits.  Pure: nothing is mutated."""
        if vram_mb > self.budget_mb:
            return AdmissionPlan(refusal=f"needs {vram_mb} MB but the whole budget is {self.budget_mb} MB")
        evictable = self._evictable(role, busy)
        evict = list(self._exclusivity_evictions(vram_mb, evictable))
        projected = self.used_mb - sum(entry.vram_mb for entry in evict)
        for entry in evictable:
            if projected + vram_mb <= self.budget_mb:
                break
            if entry not in evict:
                evict.append(entry)
                projected -= entry.vram_mb
        if projected + vram_mb > self.budget_mb:
            return AdmissionPlan(refusal=self._refusal(role, vram_mb, busy))
        return AdmissionPlan(evict=tuple(entry.role for entry in evict))

    def _evictable(self, role: ModelRole, busy: frozenset[ModelRole]) -> list[Resident]:
        """Least-recently-used first; a role serving a live call is never evicted."""
        candidates = [
            entry
            for entry in self._resident.values()
            if entry.role != role and entry.role not in busy
        ]
        return sorted(candidates, key=lambda entry: entry.last_used)

    def _exclusivity_evictions(self, vram_mb: int, evictable: list[Resident]) -> list[Resident]:
        if self.profile.allow_concurrent_gpu_models or vram_mb < HEAVYWEIGHT_VRAM_MB:
            return []
        return [entry for entry in evictable if entry.is_heavyweight]

    def _refusal(self, role: ModelRole, vram_mb: int, busy: frozenset[ModelRole]) -> str:
        blocked = sorted(name.value for name in busy if name in self._resident and name != role)
        detail = f"; busy and unevictable: {', '.join(blocked)}" if blocked else ""
        return f"needs {vram_mb} MB, {self.free_mb} MB free of {self.budget_mb} MB{detail}"

    # -- serialisation ----------------------------------------------------
    def waiting(self) -> _WaitScope:
        """Async context manager that holds the GPU lock and tracks queue depth."""
        return _WaitScope(self)


class _WaitScope:
    def __init__(self, scheduler: GpuScheduler) -> None:
        self._scheduler = scheduler

    async def __aenter__(self) -> GpuScheduler:
        self._scheduler._waiting += 1
        try:
            await self._scheduler.lock.acquire()
        finally:
            self._scheduler._waiting -= 1
        return self._scheduler

    async def __aexit__(self, *_exc: object) -> None:
        self._scheduler.lock.release()
