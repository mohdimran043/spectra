"""Redis cache backend (distributed profile).

Values are JSON encoded so a cached search result is readable by any service in
any language, and because ``json.dumps(5) == "5"`` the native ``INCRBY`` path
stays compatible with ``get``/``set`` - counters and cached documents can share
one keyspace without a second codec.
"""

from __future__ import annotations

import json
from typing import Any

from spectra_config import Settings
from spectra_config.logging import get_logger

from ..interfaces import CacheStore

log = get_logger(__name__)

SOCKET_TIMEOUT_SECONDS = 5


class RedisCacheStore(CacheStore):
    """JSON-serialising cache on top of ``redis.asyncio``."""

    backend_name = "redis"

    def __init__(self, settings: Settings) -> None:
        from redis.asyncio import Redis  # lazy: optional dependency

        self._settings = settings
        self._client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_timeout=SOCKET_TIMEOUT_SECONDS,
            socket_connect_timeout=SOCKET_TIMEOUT_SECONDS,
        )

    async def probe(self) -> None:
        """Raise unless the server answers - used by the factory at start-up."""
        await self._client.ping()

    async def get(self, key: str) -> Any | None:
        raw = await self._client.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            log.warning("cache.decode_failed", backend=self.backend_name, key=key)
            return raw

    async def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        if ttl_seconds is not None and ttl_seconds <= 0:
            raise ValueError(f"ttl_seconds must be positive when given, got {ttl_seconds}")
        payload = json.dumps(value, default=str)
        await self._client.set(key, payload, ex=ttl_seconds)

    async def delete(self, key: str) -> None:
        await self._client.delete(key)

    async def incr(self, key: str, amount: int = 1) -> int:
        return int(await self._client.incrby(key, amount))

    async def health(self) -> dict[str, Any]:
        try:
            await self._client.ping()
            size = int(await self._client.dbsize())
        except Exception as exc:  # health must never raise
            log.warning("cache.health_failed", backend=self.backend_name, error=str(exc))
            return {"backend": self.backend_name, "status": "error", "detail": str(exc)}
        return {"backend": self.backend_name, "status": "ok", "url": self._settings.redis_url, "keys": size}

    async def close(self) -> None:
        await self._client.aclose()
