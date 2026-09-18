"""Adaptive search budgets (latency / tool-call / evidence / GPU ceilings)."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .settings import Settings


@dataclass(frozen=True)
class SearchBudget:
    """Immutable budget for one investigation run."""

    mode: str
    max_tool_calls: int
    max_latency_seconds: float
    max_iterations: int
    candidate_pool_size: int
    rerank_top_k: int
    evidence_top_k: int
    allow_gpu_heavy: bool
    sufficiency_threshold: float

    def tightened(self, **overrides: object) -> SearchBudget:
        """Return a *new* budget - budgets are never mutated in place."""
        return replace(self, **overrides)  # type: ignore[arg-type]


def budget_for(mode: str, settings: Settings) -> SearchBudget:
    if mode == "fast":
        return SearchBudget(
            mode="fast",
            max_tool_calls=settings.fast_max_tool_calls,
            max_latency_seconds=settings.fast_max_latency_seconds,
            max_iterations=1,
            candidate_pool_size=min(settings.candidate_pool_size, 60),
            rerank_top_k=min(settings.rerank_top_k, 12),
            evidence_top_k=min(settings.evidence_top_k, 6),
            allow_gpu_heavy=False,
            sufficiency_threshold=settings.sufficiency_threshold,
        )
    return SearchBudget(
        mode="deep",
        max_tool_calls=settings.deep_max_tool_calls,
        max_latency_seconds=settings.deep_max_latency_seconds,
        max_iterations=settings.deep_max_iterations,
        candidate_pool_size=settings.candidate_pool_size,
        rerank_top_k=settings.rerank_top_k,
        evidence_top_k=settings.evidence_top_k,
        allow_gpu_heavy=True,
        sufficiency_threshold=settings.sufficiency_threshold,
    )
