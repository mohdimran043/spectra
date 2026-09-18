"""The baseline interface.

Five strategies answer the same questions over the same indexes.  Each declares
what it deliberately lacks, because the point of the comparison is to isolate
which architectural component earns which result.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from spectra_schemas import PermissionContext, SearchHit

from ..datasets.benchmark import BenchmarkQuestion, Target


@dataclass
class BaselineResult:
    """What a strategy produced for one question."""

    question_id: str
    answer: str = ""
    status: str = "supported"
    confidence: float = 0.0
    targets: list[Target] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    evidence_labels: list[str] = field(default_factory=list)
    contradictions: int = 0
    claims: int = 0
    latency_ms: float = 0.0
    tool_calls: int = 0
    model_calls: int = 0
    degraded: bool = False
    error: str | None = None


class Baseline(ABC):
    """One retrieval/answering strategy."""

    name: str = "abstract"
    description: str = ""
    lacks: tuple[str, ...] = ()

    def __init__(self, container: Any) -> None:
        self.container = container

    @abstractmethod
    async def answer(self, question: BenchmarkQuestion, ctx: PermissionContext) -> BaselineResult: ...

    async def timed(self, question: BenchmarkQuestion, ctx: PermissionContext) -> BaselineResult:
        """Run with timing and failure isolation - one crash must not lose a run."""
        started = time.perf_counter()
        try:
            result = await self.answer(question, ctx)
        except Exception as exc:  # noqa: BLE001 - deliberately broad, recorded not raised
            return BaselineResult(
                question_id=question.id,
                status="failed",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                error=f"{type(exc).__name__}: {exc}",
            )
        if not result.latency_ms:
            result.latency_ms = (time.perf_counter() - started) * 1000.0
        return result


def hits_to_targets(hits: list[SearchHit]) -> list[Target]:
    """Translate retrieval output into checkable citations."""
    targets: list[Target] = []
    for hit in hits:
        locator = hit.provenance.locator
        kind = getattr(locator, "kind", "document")
        if kind == "document":
            targets.append(Target("document", locator.document_id, page=locator.page))
        elif kind == "image":
            targets.append(Target("image", locator.image_id))
        elif kind == "video":
            targets.append(Target("video", locator.video_id, start_seconds=locator.start_seconds))
        elif kind == "audio":
            targets.append(Target("audio", locator.audio_id, start_seconds=locator.start_seconds))
        elif kind == "database":
            targets.append(Target("database", locator.record_id))
        else:
            targets.append(Target("external", getattr(locator, "resource", hit.asset_id)))
    return targets


def snippet_answer(hits: list[SearchHit], limit: int = 3) -> str:
    """Concatenation answer used by the non-agentic baselines.

    Cited as [E1..En] so `claim_support` can be measured on the same footing as
    SPECTRA's synthesised answer.
    """
    parts = []
    for index, hit in enumerate(hits[:limit], start=1):
        text = (hit.snippet or hit.text or "").replace("«", "").replace("»", "").strip()
        if text:
            parts.append(f"{text} [E{index}]")
    return " ".join(parts)
