"""Benchmark runner: suite x baselines, with failure isolation and resumability."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from spectra_config import REPO_ROOT
from spectra_config.logging import get_logger
from spectra_schemas import PermissionContext, Role

from ..baselines import BASELINES, Baseline, BaselineResult
from ..datasets.benchmark import BenchmarkQuestion, load_manifest, load_suites
from ..metrics import (
    abstention_outcome,
    claim_support,
    entity_resolution_prf,
    evidence_completeness,
    investigation_success,
    mrr,
    ndcg_at_k,
    percentiles,
    precision_at_k,
    recall_at_k,
)

log = get_logger(__name__)

DEFAULT_K = 10
QUESTION_TIMEOUT_SECONDS = 600.0
DEFAULT_REPORT_DIR = REPO_ROOT / "evaluation" / "spectra_eval" / "reports"


@dataclass
class QuestionScore:
    question_id: str
    category: str
    baseline: str
    recall_at_k: float = 0.0
    precision_at_k: float = 0.0
    mrr: float = 0.0
    ndcg_at_k: float = 0.0
    entity_f1: float = 0.0
    evidence_completeness: float = 0.0
    claim_support: float = 0.0
    investigation_success: float = 0.0
    abstention: str = ""
    claims: int = 0
    latency_ms: float = 0.0
    tool_calls: int = 0
    degraded: bool = False
    error: str | None = None


def score_question(question: BenchmarkQuestion, result: BaselineResult, baseline: str) -> QuestionScore:
    expected = list(question.expected_targets)
    return QuestionScore(
        question_id=question.id,
        category=question.category,
        baseline=baseline,
        recall_at_k=recall_at_k(result.targets, expected, DEFAULT_K),
        precision_at_k=precision_at_k(result.targets, expected, DEFAULT_K),
        mrr=mrr(result.targets, expected),
        ndcg_at_k=ndcg_at_k(result.targets, expected, DEFAULT_K),
        entity_f1=entity_resolution_prf(result.entities, question.expected_entities).f1,
        evidence_completeness=evidence_completeness(result.targets, expected),
        claim_support=claim_support(result.answer, result.evidence_labels),
        investigation_success=investigation_success(
            result.status, question.expected_status, result.answer, question.expected_conclusion
        ),
        abstention=abstention_outcome(result.status, question.expected_status),
        claims=result.claims,
        latency_ms=result.latency_ms,
        tool_calls=result.tool_calls,
        degraded=result.degraded,
        error=result.error,
    )


@dataclass
class RunReport:
    suite: str
    baselines: list[str]
    questions: int
    started_at: float
    finished_at: float = 0.0
    scores: list[QuestionScore] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "baselines": self.baselines,
            "questions": self.questions,
            "duration_seconds": round(self.finished_at - self.started_at, 2),
            "environment": self.environment,
            "manifest_seed": self.manifest.get("seed"),
            "manifest_scale": self.manifest.get("scale"),
            "scores": [asdict(s) for s in self.scores],
            "summary": summarise(self.scores),
        }


def summarise(scores: list[QuestionScore]) -> dict[str, Any]:
    """Per-baseline and per-(baseline, category) aggregates."""
    by_baseline: dict[str, list[QuestionScore]] = {}
    for score in scores:
        by_baseline.setdefault(score.baseline, []).append(score)

    summary: dict[str, Any] = {}
    for baseline, rows in by_baseline.items():
        summary[baseline] = {
            "overall": _aggregate(rows),
            "by_category": {
                category: _aggregate(group)
                for category, group in _group(rows, key=lambda s: s.category).items()
            },
        }
    return summary


def _group(rows: list[QuestionScore], key) -> dict[str, list[QuestionScore]]:
    grouped: dict[str, list[QuestionScore]] = {}
    for row in rows:
        grouped.setdefault(key(row), []).append(row)
    return grouped


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _aggregate(rows: list[QuestionScore]) -> dict[str, Any]:
    outcomes = _group(rows, key=lambda s: s.abstention)
    return {
        "questions": len(rows),
        "recall@10": _mean([r.recall_at_k for r in rows]),
        "precision@10": _mean([r.precision_at_k for r in rows]),
        "mrr": _mean([r.mrr for r in rows]),
        "ndcg@10": _mean([r.ndcg_at_k for r in rows]),
        "entity_f1": _mean([r.entity_f1 for r in rows]),
        "evidence_completeness": _mean([r.evidence_completeness for r in rows]),
        "claim_support": _mean([r.claim_support for r in rows]),
        "investigation_success": _mean([r.investigation_success for r in rows]),
        "abstention": {name: len(group) for name, group in sorted(outcomes.items())},
        "wrongly_answered": len(outcomes.get("wrongly_answered", [])),
        "avg_tool_calls": _mean([float(r.tool_calls) for r in rows]),
        "avg_claims": _mean([float(r.claims) for r in rows]),
        "latency_ms": percentiles([r.latency_ms for r in rows]),
        "errors": len([r for r in rows if r.error]),
        "degraded": len([r for r in rows if r.degraded]),
    }


class BenchmarkRunner:
    """Runs a suite against a set of baselines, one question at a time per baseline."""

    def __init__(self, container: Any, *, report_dir: Path | None = None) -> None:
        self.container = container
        self.report_dir = report_dir or DEFAULT_REPORT_DIR

    async def run(
        self,
        suite: str = "default",
        baselines: list[str] | None = None,
        limit: int | None = None,
        ctx: PermissionContext | None = None,
    ) -> dict[str, Any]:
        suites = load_suites()
        if suite not in suites:
            raise KeyError(f"unknown suite {suite!r}; available: {sorted(suites)}")
        questions = suites[suite][:limit] if limit else suites[suite]
        names = baselines or list(BASELINES)
        permissions = ctx or PermissionContext(user_id="benchmark", role=Role.ANALYST)

        report = RunReport(
            suite=suite,
            baselines=names,
            questions=len(questions),
            started_at=time.time(),
            manifest=_safe_manifest(),
            environment=await self._environment(),
        )

        for name in names:
            baseline = self._build(name)
            log.info("benchmark.baseline_started", baseline=name, questions=len(questions))
            for question in questions:
                score = await self._run_one(baseline, question, permissions)
                report.scores.append(score)
                self._checkpoint(report)
            log.info("benchmark.baseline_finished", baseline=name)

        report.finished_at = time.time()
        payload = report.to_dict()
        self._write(report.suite, payload)
        return payload

    async def _run_one(
        self, baseline: Baseline, question: BenchmarkQuestion, ctx: PermissionContext
    ) -> QuestionScore:
        try:
            result = await asyncio.wait_for(
                baseline.timed(question, ctx), timeout=QUESTION_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            result = BaselineResult(
                question_id=question.id,
                status="failed",
                error=f"timed out after {QUESTION_TIMEOUT_SECONDS:.0f}s",
                latency_ms=QUESTION_TIMEOUT_SECONDS * 1000.0,
            )
        if result.error:
            log.warning("benchmark.question_failed", question=question.id,
                        baseline=baseline.name, error=result.error)
        return score_question(question, result, baseline.name)

    def _build(self, name: str) -> Baseline:
        if name not in BASELINES:
            raise KeyError(f"unknown baseline {name!r}; available: {sorted(BASELINES)}")
        return BASELINES[name](self.container)

    async def _environment(self) -> dict[str, Any]:
        environment: dict[str, Any] = {"backends": {}, "models": {}}
        gateway = getattr(self.container, "gateway", None)
        if gateway is not None:
            status = await gateway.status()
            environment["models"] = {
                info.role.value: f"{info.active_runtime}/{info.active_model}"
                for info in status.models
            }
            environment["gpu_available"] = status.gpu.available
            environment["degraded"] = status.degraded
            environment["degraded_reasons"] = status.degraded_reasons[:5]
        settings = getattr(self.container, "settings", None)
        if settings is not None:
            environment["backends"] = {
                "vector": settings.vector_backend.value,
                "lexical": settings.lexical_backend.value,
                "graph": settings.graph_backend.value,
                "relational": settings.relational_backend.value,
            }
        return environment

    def _checkpoint(self, report: RunReport) -> None:
        """Write partial results after every question, so a crash loses nothing."""
        self.report_dir.mkdir(parents=True, exist_ok=True)
        path = self.report_dir / f"{report.suite}.partial.json"
        path.write_text(json.dumps({"scores": [asdict(s) for s in report.scores]}, indent=2))

    def _write(self, suite: str, payload: dict[str, Any]) -> Path:
        from ..reports.report import render_markdown

        self.report_dir.mkdir(parents=True, exist_ok=True)
        json_path = self.report_dir / f"{suite}.json"
        json_path.write_text(json.dumps(payload, indent=2))
        md_path = self.report_dir / f"{suite}.md"
        md_path.write_text(render_markdown(payload))
        partial = self.report_dir / f"{suite}.partial.json"
        if partial.exists():
            partial.unlink()
        log.info("benchmark.report_written", json=str(json_path), markdown=str(md_path))
        return json_path


def _safe_manifest() -> dict[str, Any]:
    try:
        return load_manifest()
    except FileNotFoundError:
        return {}
