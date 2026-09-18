"""Bounded event log surfaced by ``status()`` so operators can see what the manager did."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from spectra_config.logging import get_logger
from spectra_schemas import ModelEvent, ModelRole

log = get_logger(__name__)

MAX_EVENTS = 50

# Event names, kept as constants so the API and UI can match on them.
EVENT_SELECTED = "selected"
EVENT_LOADED = "loaded"
EVENT_UNLOADED = "unloaded"
EVENT_EVICTED_FOR_SPACE = "evicted_for_space"
EVENT_EVICTED_IDLE = "evicted_idle"
EVENT_OOM = "oom"
EVENT_OOM_REDUCED = "oom_retry_reduced"
EVENT_OOM_EVICTED_PEERS = "oom_evicted_peers"
EVENT_OOM_NEXT_CANDIDATE = "oom_next_candidate"
EVENT_OOM_DETERMINISTIC = "oom_deterministic_fallback"
EVENT_CALL_FAILED = "call_failed"
EVENT_RETRY = "retry"
EVENT_FALLBACK_ROLE = "fallback_role"
EVENT_DEGRADED = "degraded"
EVENT_UNAVAILABLE = "unavailable"


class EventLog:
    """A fixed-size ring of :class:`ModelEvent`, newest last."""

    def __init__(self, capacity: int = MAX_EVENTS) -> None:
        self._events: deque[ModelEvent] = deque(maxlen=capacity)

    def record(self, role: ModelRole, event: str, detail: str = "", vram_mb: int = 0) -> ModelEvent:
        entry = ModelEvent(role=role, event=event, detail=detail, vram_mb=vram_mb)
        self._events.append(entry)
        log.info(f"runtime.{event}", role=role.value, detail=detail, vram_mb=vram_mb)
        return entry

    def recent(self) -> list[ModelEvent]:
        return list(self._events)

    def extend(self, entries: Iterable[ModelEvent]) -> None:
        self._events.extend(entries)

    def __len__(self) -> int:
        return len(self._events)
