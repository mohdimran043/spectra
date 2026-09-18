"""Strict-JSON model calls.

Every generative step in the Brain is schema-constrained and every one of them
must survive the model being unavailable, so this helper always returns an
outcome object - never an exception - and says plainly when it degraded.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from spectra_config.logging import get_logger
from spectra_schemas import ModelRole

log = get_logger(__name__)

_JSON_BLOCK = re.compile(r"\{.*\}", re.S)


@dataclass(frozen=True)
class LlmOutcome:
    """Result of one structured model call."""

    data: dict[str, Any] | None = None
    degraded: bool = True
    reason: str | None = "model not consulted"
    model: str = ""
    latency_ms: float = 0.0

    @property
    def ok(self) -> bool:
        return self.data is not None and not self.degraded


async def structured(
    gateway: Any | None,
    *,
    messages: Sequence[Any],
    schema: dict[str, Any],
    role: ModelRole = ModelRole.DEEP_BRAIN,
    max_tokens: int = 768,
    temperature: float = 0.1,
) -> LlmOutcome:
    """Call a model for a JSON object, degrading cleanly when it cannot."""
    if gateway is None:
        return LlmOutcome(reason="no model gateway is configured")
    role_available = getattr(gateway, "role_available", None)
    if role_available is not None and not role_available(role):
        return LlmOutcome(reason=f"model role '{role.value}' is unavailable")
    try:
        result = await gateway.generate(
            list(messages),
            role=role,
            max_tokens=max_tokens,
            temperature=temperature,
            json_schema=schema,
        )
    except Exception as exc:
        log.warning("llm.call_failed", role=role.value, error=str(exc))
        return LlmOutcome(reason=f"model call failed: {type(exc).__name__}")

    if getattr(result, "degraded", False):
        return LlmOutcome(
            reason=getattr(result, "degraded_reason", None) or "model reported degraded output",
            model=getattr(result, "model", ""),
            latency_ms=getattr(result, "latency_ms", 0.0),
        )
    payload = getattr(result, "structured", None) or _parse(getattr(result, "text", ""))
    if not isinstance(payload, dict):
        return LlmOutcome(
            reason="model did not return a JSON object",
            model=getattr(result, "model", ""),
            latency_ms=getattr(result, "latency_ms", 0.0),
        )
    return LlmOutcome(
        data=payload,
        degraded=False,
        reason=None,
        model=getattr(result, "model", ""),
        latency_ms=getattr(result, "latency_ms", 0.0),
    )


def _parse(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = _JSON_BLOCK.search(text)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def text_messages(system: str, user: str) -> list[Any]:
    """Build the two-message chat payload every structured call uses."""
    from spectra_ai_core.interfaces import ChatMessage

    return [ChatMessage(role="system", content=system), ChatMessage(role="user", content=user)]
