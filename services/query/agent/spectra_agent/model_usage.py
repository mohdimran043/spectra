"""Records which models actually answered, for the metrics and the autopsy.

A transparent proxy: everything except ``generate`` passes straight through to
the real gateway, so injecting it changes no behaviour.
"""

from __future__ import annotations

from typing import Any


class ModelUsageRecorder:
    """Wraps a model gateway and remembers the models it used."""

    def __init__(self, gateway: Any | None) -> None:
        self._gateway = gateway
        self._calls: list[tuple[str, float]] = []

    def __getattr__(self, name: str) -> Any:
        if self._gateway is None:
            raise AttributeError(name)
        return getattr(self._gateway, name)

    @property
    def wrapped(self) -> Any | None:
        return self._gateway

    async def generate(self, *args: Any, **kwargs: Any) -> Any:
        if self._gateway is None:
            raise RuntimeError("no model gateway is configured")
        result = await self._gateway.generate(*args, **kwargs)
        model = getattr(result, "model", "") or "unknown"
        self._calls.append((model, float(getattr(result, "latency_ms", 0.0))))
        return result

    def snapshot(self) -> tuple[list[str], dict[str, float]]:
        """(distinct models used, cumulative latency per model)."""
        models: list[str] = []
        latency: dict[str, float] = {}
        for model, elapsed in self._calls:
            if model not in models:
                models.append(model)
            latency[model] = round(latency.get(model, 0.0) + elapsed, 3)
        return models, latency


def wrap(gateway: Any | None) -> ModelUsageRecorder | None:
    return ModelUsageRecorder(gateway) if gateway is not None else None
