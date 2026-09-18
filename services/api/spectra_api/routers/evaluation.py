"""Research/thesis mode: benchmark suites and baseline comparison."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..dependencies import Container, Ctx, CtxAutopsy
from ..errors import DependencyUnavailable, ValidationRejected

router = APIRouter(tags=["evaluation"])

KNOWN_BASELINES = ("bm25", "vector_rag", "multimodal_rag", "agentic", "spectra")


class EvalRequest(BaseModel):
    suite: str = "default"
    baselines: list[str] = Field(default_factory=lambda: list(KNOWN_BASELINES))
    limit: int | None = None


def _load_eval():
    try:
        from spectra_eval.runners.runner import BenchmarkRunner

        return BenchmarkRunner
    except ImportError as exc:
        raise DependencyUnavailable("evaluation", f"the evaluation harness is unavailable: {exc}")


@router.get("/eval/benchmarks")
async def list_benchmarks(container: Container, ctx: Ctx) -> dict[str, Any]:
    from spectra_eval.datasets.benchmark import load_suites

    suites = load_suites()
    return {
        "baselines": list(KNOWN_BASELINES),
        "suites": {
            name: {"questions": len(qs), "categories": sorted({q.category for q in qs})}
            for name, qs in suites.items()
        },
    }


@router.post("/eval/run")
async def run_evaluation(
    body: EvalRequest, container: Container, ctx: CtxAutopsy
) -> dict[str, Any]:
    unknown = [b for b in body.baselines if b not in KNOWN_BASELINES]
    if unknown:
        raise ValidationRejected(f"unknown baselines: {', '.join(unknown)}")
    runner_cls = _load_eval()
    runner = runner_cls(container=container)
    return await runner.run(suite=body.suite, baselines=body.baselines, limit=body.limit)
