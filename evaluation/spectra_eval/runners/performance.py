"""Scale benchmarks: ingestion rate and query latency at the specified tiers."""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from spectra_config import REPO_ROOT
from spectra_config.logging import get_logger
from spectra_schemas import PermissionContext, Role, SearchMode, SearchRequest

from ..metrics import percentiles

log = get_logger(__name__)

# The tiers the specification calls for.
TIERS: dict[str, dict[str, int]] = {
    "small": {"documents": 100, "images": 1_000, "videos": 10, "records": 10_000},
    "medium": {"documents": 1_000, "images": 10_000, "videos": 100, "records": 100_000},
}
QUERY_SAMPLES = 20
WARMUP_QUERIES = 3

PROBE_QUERIES = (
    "authentication timeout",
    "connection pool exhausted",
    "failed payment for the enterprise segment",
    "architecture change discussion",
    "incident approval decision",
)


@dataclass
class StageTiming:
    stage: str
    samples: list[float] = field(default_factory=list)

    def summary(self) -> dict[str, float]:
        return percentiles(self.samples)


@dataclass
class PerformanceReport:
    scale: str
    corpus: dict[str, int] = field(default_factory=dict)
    ingestion: dict[str, Any] = field(default_factory=dict)
    query: dict[str, Any] = field(default_factory=dict)
    stages: dict[str, dict[str, float]] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PerformanceRunner:
    """Measures the query path against whatever is already indexed.

    Ingestion rate is measured by the caller feeding a corpus in; this runner
    reports the index size it found and then times the read path, because that
    is the number that must stay flat as the corpus grows.
    """

    def __init__(self, container: Any, *, report_dir: Path | None = None) -> None:
        self.container = container
        self.report_dir = report_dir or REPO_ROOT / "evaluation" / "spectra_eval" / "reports"

    async def run(self, scale: str = "small", samples: int = QUERY_SAMPLES) -> dict[str, Any]:
        stats = await self.container.storage.repository.stats()
        report = PerformanceReport(
            scale=scale,
            corpus={
                "assets": stats.get("assets", 0),
                "chunks": stats.get("chunks", 0),
                "entities": stats.get("entities", 0),
                "entity_links": stats.get("entity_links", 0),
            },
            environment=await self._environment(),
        )

        ctx = PermissionContext(user_id="perf", role=Role.ANALYST)
        await self._warmup(ctx)

        latencies: list[float] = []
        stage_timings: dict[str, StageTiming] = {}
        for index in range(samples):
            query = PROBE_QUERIES[index % len(PROBE_QUERIES)]
            started = time.perf_counter()
            response = await self.container.search.search(
                SearchRequest(query=query, mode=SearchMode.FAST, top_k=10), ctx
            )
            latencies.append((time.perf_counter() - started) * 1000.0)
            for stage in response.stages:
                stage_timings.setdefault(stage.stage, StageTiming(stage.stage)).samples.append(
                    stage.latency_ms
                )

        report.query = {
            "samples": len(latencies),
            "latency_ms": percentiles(latencies),
            "queries_per_second": round(1000.0 / statistics.mean(latencies), 3) if latencies else 0.0,
        }
        report.stages = {name: timing.summary() for name, timing in sorted(stage_timings.items())}
        report.ingestion = {
            "note": "ingestion rate is measured by `make seed-demo`, which reports assets/second",
            "indexed_chunks": report.corpus["chunks"],
        }

        self._write(report)
        return report.to_dict()

    async def _warmup(self, ctx: PermissionContext) -> None:
        """Exclude first-call model loading from the measurement."""
        for index in range(WARMUP_QUERIES):
            await self.container.search.search(
                SearchRequest(query=PROBE_QUERIES[index % len(PROBE_QUERIES)],
                              mode=SearchMode.FAST, top_k=10),
                ctx,
            )

    async def _environment(self) -> dict[str, Any]:
        gateway = getattr(self.container, "gateway", None)
        if gateway is None:
            return {}
        status = await gateway.status()
        return {
            "gpu_available": status.gpu.available,
            "profile": status.profile,
            "models": {i.role.value: f"{i.active_runtime}/{i.active_model}" for i in status.models},
        }

    def _write(self, report: PerformanceReport) -> Path:
        self.report_dir.mkdir(parents=True, exist_ok=True)
        path = self.report_dir / f"performance-{report.scale}.json"
        path.write_text(json.dumps(report.to_dict(), indent=2))
        log.info("performance.report_written", path=str(path))
        return path


async def main(scale: str = "small") -> dict[str, Any]:
    from spectra_api.container import build_container, shutdown_container

    container = await build_container()
    try:
        return await PerformanceRunner(container).run(scale=scale)
    finally:
        await shutdown_container()


if __name__ == "__main__":  # pragma: no cover - CLI
    import sys

    print(json.dumps(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "small")), indent=2))
