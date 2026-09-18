"""Selectable answering strategies, from pure lexical retrieval to full SPECTRA."""

from .agentic import AgenticBaseline
from .base import Baseline, BaselineResult, hits_to_targets, snippet_answer
from .retrieval_only import Bm25Baseline, MultimodalRagBaseline, VectorRagBaseline
from .spectra import SpectraBaseline, result_from_state

BASELINES: dict[str, type[Baseline]] = {
    Bm25Baseline.name: Bm25Baseline,
    VectorRagBaseline.name: VectorRagBaseline,
    MultimodalRagBaseline.name: MultimodalRagBaseline,
    AgenticBaseline.name: AgenticBaseline,
    SpectraBaseline.name: SpectraBaseline,
}

__all__ = [
    "BASELINES",
    "AgenticBaseline",
    "Baseline",
    "BaselineResult",
    "Bm25Baseline",
    "MultimodalRagBaseline",
    "SpectraBaseline",
    "VectorRagBaseline",
    "hits_to_targets",
    "result_from_state",
    "snippet_answer",
]
