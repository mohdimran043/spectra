"""SPECTRA staged retrieval: index-only, permission-aware, explainable search."""

from __future__ import annotations

from .cache import SEARCH_CACHE_TTL_SECONDS, build_cache_key
from .candidates import RRF_K, Candidate, FusedCandidate, rrf_fuse
from .scoring import ScoredCandidate, ScoreInput, ScoringWeights, UnifiedScorer
from .service import SearchService
from .snippets import build_snippet, query_terms
from .stages import (
    StageContext,
    assemble_hits,
    filter_candidates,
    fuse_and_rerank,
    generate_candidates,
    score_candidates,
)

__all__ = [
    "Candidate",
    "FusedCandidate",
    "RRF_K",
    "SEARCH_CACHE_TTL_SECONDS",
    "ScoreInput",
    "ScoredCandidate",
    "ScoringWeights",
    "SearchService",
    "StageContext",
    "UnifiedScorer",
    "assemble_hits",
    "build_cache_key",
    "build_snippet",
    "filter_candidates",
    "fuse_and_rerank",
    "generate_candidates",
    "query_terms",
    "rrf_fuse",
    "score_candidates",
]
