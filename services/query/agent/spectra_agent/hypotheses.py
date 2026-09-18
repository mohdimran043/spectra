"""Compatibility shim - the Hypothesis Engine moved into its own agent package.

It now lives at :mod:`spectra_agent.agents.hypothesis`, next to the causal
lexicon it mines with.  This module stays because ``spectra_agent.hypotheses``
is a published import path: ``state_ops`` and the grounding tests reach for
``focal_terms`` through it.  Nothing is defined here - import from
``spectra_agent.agents.hypothesis`` in new code.
"""

from __future__ import annotations

from .agents.hypothesis.hypotheses import (
    HYPOTHESIS_SCHEMA,
    MAX_PRIOR,
    MIN_PRIOR,
    SYSTEM_PROMPT,
    HypothesisEngine,
    focal_terms,
)

__all__ = [
    "HYPOTHESIS_SCHEMA",
    "MAX_PRIOR",
    "MIN_PRIOR",
    "SYSTEM_PROMPT",
    "HypothesisEngine",
    "focal_terms",
]
