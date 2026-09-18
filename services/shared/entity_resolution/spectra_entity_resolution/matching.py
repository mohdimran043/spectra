"""Fuzzy and semantic similarity helpers for the resolution cascade.

Both steps answer the same question - *how close is this surface form to a
candidate entity?* - but with different failure modes, so they are kept apart and
each carries its own documented threshold.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from rapidfuzz import fuzz
from spectra_schemas import CanonicalEntity

# ---------------------------------------------------------------------------
# Thresholds.
#
# WRatio is rapidfuzz's general-purpose blend; on enterprise names (short, high
# information density) 88 is the point where "Mohammed Imran" still matches
# "Mohammad Imran" but stops matching "Mohammed Ismail".  token_set_ratio ignores
# word order and duplicates, so it over-matches more easily and is held to a
# stricter 92.  Both are on rapidfuzz's 0-100 scale and divided by 100 here.
# ---------------------------------------------------------------------------
FUZZY_WRATIO_THRESHOLD = 88.0
FUZZY_TOKEN_SET_THRESHOLD = 92.0
_RAPIDFUZZ_SCALE = 100.0

#: Cosine similarity above which an embedding match is worth reporting at all.
#: Below this, bi-encoder neighbours are topical rather than co-referent.
SEMANTIC_COSINE_THRESHOLD = 0.72

#: How many repository candidates the fuzzy/semantic steps consider.  Bounded so
#: resolution stays O(1) in corpus size.
CANDIDATE_POOL_LIMIT = 25


@dataclass(frozen=True)
class FuzzyMatch:
    entity_id: str
    score: float
    matched_alias: str
    metric: str


def surfaces_of(entity: CanonicalEntity) -> tuple[str, ...]:
    """Canonical name plus every recorded alias, de-duplicated, order preserved."""
    seen: dict[str, None] = {}
    for value in (entity.canonical_name, *entity.aliases):
        cleaned = value.strip()
        if cleaned:
            seen.setdefault(cleaned, None)
    return tuple(seen)


def best_fuzzy_match(surface: str, entity: CanonicalEntity) -> FuzzyMatch | None:
    """Strongest above-threshold fuzzy match between ``surface`` and ``entity``."""
    best: FuzzyMatch | None = None
    for alias in surfaces_of(entity):
        for metric, score, threshold in (
            ("wratio", fuzz.WRatio(surface, alias), FUZZY_WRATIO_THRESHOLD),
            ("token_set", fuzz.token_set_ratio(surface, alias), FUZZY_TOKEN_SET_THRESHOLD),
        ):
            if score < threshold:
                continue
            normalised = float(score) / _RAPIDFUZZ_SCALE
            if best is None or normalised > best.score:
                best = FuzzyMatch(entity.entity_id, normalised, alias, metric)
    return best


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine similarity clamped to ``[0, 1]`` - negative similarity is no match."""
    a = np.asarray(left, dtype=np.float32)
    b = np.asarray(right, dtype=np.float32)
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denominator == 0.0:
        return 0.0
    return max(0.0, min(1.0, float(np.dot(a, b)) / denominator))
