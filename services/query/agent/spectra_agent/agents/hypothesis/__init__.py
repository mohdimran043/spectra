"""Hypothesis Engine - the explanations the investigation is trying to break.

A cognition agent, not a retrieval one: it exposes no tool.  It reads the
evidence gathered so far, mines it for causal categories and error codes, and
proposes a small ranked set of competing explanations with priors, which the
Brain then tries to disprove.  ``causal_lexicon`` is the vocabulary it mines
with - negations, competing outcomes and salient terms - and the disproof,
verifier, contradiction and stance paths borrow that same vocabulary so the
whole system argues in one language.

Switched off with the ``hypothesis`` deployment flag.
"""

from __future__ import annotations

from .causal_lexicon import (
    CAUSAL_CATEGORIES,
    NEGATION_MAP,
    CausalCategory,
    competing_outcomes,
    disproof_queries,
    negate,
    salient_terms,
)
from .hypotheses import HypothesisEngine, focal_terms

__all__ = [
    "CAUSAL_CATEGORIES",
    "NEGATION_MAP",
    "CausalCategory",
    "HypothesisEngine",
    "competing_outcomes",
    "disproof_queries",
    "focal_terms",
    "negate",
    "salient_terms",
]
