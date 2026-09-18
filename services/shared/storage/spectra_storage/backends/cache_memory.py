"""In-process cache with TTL expiry - the embedded cache backend.

Agent state, query caches and job progress all live here on a single-node
install.  Entries are stored as ``(value, expires_at)`` pairs and lazily swept on
access, and every mutation replaces the dict rather than editing it in place, so
a concurrent reader can never observe a half-updated map.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from spectra_config import Settings
from spectra_config.logging import get_logger

from ..interfaces import CacheStore

log = get_logger(__name__)

NO_EXPIRY = float("inf")
SWEEP_EVERY_OPERATIONS = 256


class MemoryCacheStore(CacheStore):
    """Process-local TTL cache guarded by an asyncio lock."""

    backend_name = "memory"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings
        self._entries: dict[str, tuple[Any, float]] = {}
        self._lock = asyncio.Lock()
        self._operations = 0

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if expires_at <= time.monotonic():
                self._entries = {k: v for k, v in self._entries.items() if k != key}
                return None
            return value

    async def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        if ttl_seconds is not None and ttl_seconds <= 0:
            raise ValueError(f"ttl_seconds must be positive when given, got {ttl_seconds}")
        expires_at = NO_EXPIRY if ttl_seconds is None else time.monotonic() + ttl_seconds
        async with self._lock:
            self._entries = {**self._entries, key: (value, expires_at)}
            self._maybe_sweep()

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._entries = {k: v for k, v in self._entries.items() if k != key}

    async def incr(self, key: str, amount: int = 1) -> int:
        async with self._lock:
            entry = self._entries.get(key)
            current = 0
            expires_at = NO_EXPIRY
            if entry is not None and entry[1] > time.monotonic():
                current = _as_int(key, entry[0])
                expires_at = entry[1]
            updated = current + amount
            self._entries = {**self._entries, key: (updated, expires_at)}
            return updated

    async def health(self) -> dict[str, Any]:
        async with self._lock:
            return {"backend": self.backend_name, "status": "ok", "entries": len(self._entries)}

    async def close(self) -> None:
        async with self._lock:
            self._entries = {}

    def _maybe_sweep(self) -> None:
        self._operations += 1
        if self._operations % SWEEP_EVERY_OPERATIONS:
            return
        now = time.monotonic()
        live = {k: v for k, v in self._entries.items() if v[1] > now}
        if len(live) != len(self._entries):
            log.debug("cache.swept", backend=self.backend_name, removed=len(self._entries) - len(live))
        self._entries = live


def _as_int(key: str, value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"cache key {key!r} holds a non-numeric value and cannot be incremented") from exc
