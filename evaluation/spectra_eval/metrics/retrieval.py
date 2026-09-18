"""Ranked-retrieval metrics.

Pure functions over (ranked produced targets, expected targets) so they can be
unit-tested against hand-computed values - which they are.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from ..datasets.benchmark import Target


def _hit_positions(produced: Sequence[Target], expected: Sequence[Target]) -> list[int]:
    """1-based ranks at which a produced target satisfies some expectation."""
    positions: list[int] = []
    satisfied: set[str] = set()
    for rank, candidate in enumerate(produced, start=1):
        for want in expected:
            if want.key() in satisfied:
                continue
            if want.matches(candidate):
                satisfied.add(want.key())
                positions.append(rank)
                break
    return positions


def recall_at_k(produced: Sequence[Target], expected: Sequence[Target], k: int = 10) -> float:
    if not expected:
        return 1.0
    found = len(_hit_positions(produced[:k], expected))
    return round(found / len(expected), 6)


def precision_at_k(produced: Sequence[Target], expected: Sequence[Target], k: int = 10) -> float:
    window = produced[:k]
    if not window:
        return 0.0
    relevant = sum(1 for c in window if any(w.matches(c) for w in expected))
    return round(relevant / len(window), 6)


def mrr(produced: Sequence[Target], expected: Sequence[Target]) -> float:
    """Reciprocal rank of the first correct citation."""
    positions = _hit_positions(produced, expected)
    return round(1.0 / positions[0], 6) if positions else 0.0


def ndcg_at_k(produced: Sequence[Target], expected: Sequence[Target], k: int = 10) -> float:
    """Binary-gain nDCG: every expected target is equally relevant."""
    if not expected:
        return 1.0
    gains = [1.0 if any(w.matches(c) for w in expected) else 0.0 for c in produced[:k]]
    dcg = sum(g / math.log2(rank + 1) for rank, g in enumerate(gains, start=1))
    ideal_hits = min(len(expected), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return round(dcg / idcg, 6) if idcg else 0.0


def hit_rate(produced: Sequence[Target], expected: Sequence[Target], k: int = 10) -> float:
    """Did we get *anything* right in the top k?"""
    return 1.0 if _hit_positions(produced[:k], expected) else 0.0
