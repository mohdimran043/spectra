"""Shared HTTP plumbing for the network-backed providers (Ollama, OpenAI-shaped)."""

from __future__ import annotations

from typing import Any

import httpx

AVAILABILITY_TIMEOUT_SECONDS = 3.0
DEFAULT_CALL_TIMEOUT_SECONDS = 120.0
CONNECT_TIMEOUT_SECONDS = 5.0


class HttpProviderMixin:
    """Lazy, reusable :class:`httpx.AsyncClient` with a short-lived probe path."""

    call_timeout_seconds: float = DEFAULT_CALL_TIMEOUT_SECONDS

    @property
    def client(self) -> httpx.AsyncClient:
        existing = getattr(self, "_http_client", None)
        if existing is None or existing.is_closed:
            existing = httpx.AsyncClient(
                timeout=httpx.Timeout(self.call_timeout_seconds, connect=CONNECT_TIMEOUT_SECONDS)
            )
            self._http_client = existing
        return existing

    async def aclose(self) -> None:
        existing = getattr(self, "_http_client", None)
        if existing is not None and not existing.is_closed:
            await existing.aclose()
        self._http_client = None

    @staticmethod
    async def probe_json(url: str, headers: dict[str, str] | None = None) -> tuple[dict[str, Any] | None, str]:
        """GET ``url`` with a short timeout.  Returns ``(payload, error)``; never raises."""
        try:
            async with httpx.AsyncClient(timeout=AVAILABILITY_TIMEOUT_SECONDS) as client:
                response = await client.get(url, headers=headers or {})
            if response.status_code >= 400:
                return None, f"HTTP {response.status_code} from {url}"
            return response.json(), ""
        except Exception as exc:
            return None, f"{type(exc).__name__} contacting {url}: {exc}"


def describe_http_error(exc: Exception, url: str) -> str:
    return f"{type(exc).__name__} calling {url}: {exc}"
