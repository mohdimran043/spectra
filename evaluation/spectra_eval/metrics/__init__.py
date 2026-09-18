"""Evaluation metrics - pure functions, unit-tested against known values."""

from .quality import (
    PRF,
    abstention_outcome,
    claim_support,
    entity_resolution_prf,
    evidence_completeness,
    investigation_success,
    percentiles,
    term_overlap,
)
from .retrieval import hit_rate, mrr, ndcg_at_k, precision_at_k, recall_at_k

__all__ = [
    "PRF",
    "abstention_outcome",
    "claim_support",
    "entity_resolution_prf",
    "evidence_completeness",
    "hit_rate",
    "investigation_success",
    "mrr",
    "ndcg_at_k",
    "percentiles",
    "precision_at_k",
    "recall_at_k",
    "term_overlap",
]
