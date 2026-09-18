"""In-process metrics registry.

Deliberately dependency-free: counters + latency reservoirs that can be rendered
as JSON or in Prometheus exposition format.  A production deployment can swap
this for a real client without touching call sites.
"""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass, field

RESERVOIR_SIZE = 512


@dataclass
class LatencySeries:
    samples: deque[float] = field(default_factory=lambda: deque(maxlen=RESERVOIR_SIZE))
    count: int = 0
    total: float = 0.0

    def observe(self, value: float) -> None:
        self.samples.append(value)
        self.count += 1
        self.total += value

    def percentile(self, pct: float) -> float:
        if not self.samples:
            return 0.0
        ordered = sorted(self.samples)
        index = min(int(round(pct / 100.0 * (len(ordered) - 1))), len(ordered) - 1)
        return round(ordered[index], 3)

    def summary(self) -> dict[str, float]:
        return {
            "count": self.count,
            "mean_ms": round(self.total / self.count, 3) if self.count else 0.0,
            "p50_ms": self.percentile(50),
            "p95_ms": self.percentile(95),
            "p99_ms": self.percentile(99),
        }


class MetricsRegistry:
    """Thread-safe counters and latency series."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = defaultdict(int)
        self._latency: dict[str, LatencySeries] = defaultdict(LatencySeries)
        self._gauges: dict[str, float] = {}

    def incr(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] += amount

    def observe(self, name: str, value_ms: float) -> None:
        with self._lock:
            self._latency[name].observe(value_ms)

    def gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = value

    def record_request(self, route: str, status_code: int, latency_ms: float) -> None:
        self.incr(f"http_requests_total{{route={route},status={status_code}}}")
        self.observe(f"http_request_duration{{route={route}}}", latency_ms)

    def record_model_call(self, role: str, latency_ms: float, ok: bool) -> None:
        self.incr(f"model_calls_total{{role={role},ok={str(ok).lower()}}}")
        self.observe(f"model_latency{{role={role}}}", latency_ms)

    def record_stage(self, stage: str, latency_ms: float) -> None:
        self.observe(f"retrieval_stage_latency{{stage={stage}}}", latency_ms)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "latency": {k: v.summary() for k, v in self._latency.items()},
            }

    def prometheus(self) -> str:
        lines: list[str] = []
        with self._lock:
            for name, value in sorted(self._counters.items()):
                lines.append(f"spectra_{_sanitise(name)} {value}")
            for name, value in sorted(self._gauges.items()):
                lines.append(f"spectra_{_sanitise(name)} {value}")
            for name, series in sorted(self._latency.items()):
                base = _sanitise(name)
                summary = series.summary()
                for suffix, value in summary.items():
                    lines.append(f"spectra_{base}_{suffix} {value}")
        return "\n".join(lines) + "\n"


def _sanitise(name: str) -> str:
    out = []
    for ch in name:
        out.append(ch if ch.isalnum() or ch in "_{}=," else "_")
    return "".join(out)


def iter_names(values: Iterable[str]) -> list[str]:
    return sorted(set(values))


METRICS = MetricsRegistry()
