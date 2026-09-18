"""Candidate records and Reciprocal Rank Fusion.

Each retriever (exact-id, BM25, dense ANN, multimodal ANN) produces its own
ranked list with its own incomparable score scale.  RRF fuses them using *rank*
only, which is precisely why it is robust: a BM25 score of 14.2 and a cosine of
0.71 never have to be made commensurable.

    rrf(d) = sum over retrievers of 1 / (k + rank(d))

``k`` damps the influence of the very top of each list; the value 60 is the one
from Cormack et al. (2009) and is the de-facto default in hybrid search.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

#: Reciprocal Rank Fusion damping constant.
RRF_K = 60

RETRIEVER_EXACT = "exact_id"
RETRIEVER_ENTITY = "entity"
RETRIEVER_LEXICAL = "lexical"
RETRIEVER_DENSE = "dense"
RETRIEVER_MULTIMODAL = "multimodal"

#: Which unified-scoring signal each retriever's raw score feeds.
RETRIEVER_SIGNALS: dict[str, str] = {
    RETRIEVER_EXACT: "entity_match",
    RETRIEVER_ENTITY: "entity_match",
    RETRIEVER_LEXICAL: "lexical",
    RETRIEVER_DENSE: "semantic",
    RETRIEVER_MULTIMODAL: "semantic",
}

#: Retrievers whose hits mean "this chunk literally contains the id the user typed".
EXACT_RETRIEVERS = frozenset({RETRIEVER_EXACT, RETRIEVER_ENTITY})


@dataclass(frozen=True)
class Candidate:
    """One chunk proposed by one retriever."""

    chunk_id: str
    retriever: str
    rank: int
    score: float
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FusedCandidate:
    """A chunk after fusion, carrying every retriever's evidence for it."""

    chunk_id: str
    rrf_score: float
    retrievers: tuple[str, ...]
    ranks: Mapping[str, int]
    signals: Mapping[str, float]

    @property
    def is_exact(self) -> bool:
        return any(retriever in EXACT_RETRIEVERS for retriever in self.retrievers)


def rank_candidates(chunk_ids: Sequence[str], retriever: str, scores: Sequence[float]) -> tuple[Candidate, ...]:
    """Build a ranked candidate list (rank is 1-based, ties keep input order)."""
    return tuple(
        Candidate(chunk_id=chunk_id, retriever=retriever, rank=index + 1, score=float(score))
        for index, (chunk_id, score) in enumerate(zip(chunk_ids, scores, strict=False))
    )


def renumber(candidates: Sequence[Candidate]) -> tuple[Candidate, ...]:
    """De-duplicate and re-rank a list so it is contiguous and counted once.

    Two things matter here.  Fusion uses ranks, so a permission-filtered hole
    would otherwise silently penalise every document behind it; and a chunk that
    two sub-queries of the *same* retriever both returned must contribute to that
    retriever's RRF term once, at its best rank, not twice.
    """
    best: dict[str, Candidate] = {}
    for candidate in sorted(candidates, key=lambda item: (item.rank, -item.score)):
        best.setdefault(candidate.chunk_id, candidate)
    return tuple(
        Candidate(c.chunk_id, c.retriever, index + 1, c.score, c.payload)
        for index, c in enumerate(sorted(best.values(), key=lambda item: item.rank))
    )


def rrf_fuse(lists: Mapping[str, Sequence[Candidate]], *, k: int = RRF_K) -> tuple[FusedCandidate, ...]:
    """Fuse ranked lists into one pool ordered by descending RRF score."""
    fused: dict[str, dict[str, Any]] = {}
    for retriever, candidates in lists.items():
        for candidate in candidates:
            entry = fused.setdefault(
                candidate.chunk_id,
                {"rrf": 0.0, "retrievers": [], "ranks": {}, "signals": {}},
            )
            entry["rrf"] += 1.0 / (k + candidate.rank)
            entry["retrievers"].append(retriever)
            entry["ranks"][retriever] = candidate.rank
            _record_signal(entry["signals"], retriever, candidate.score)
    ordered = sorted(fused.items(), key=lambda item: (-item[1]["rrf"], item[0]))
    return tuple(
        FusedCandidate(
            chunk_id=chunk_id,
            rrf_score=entry["rrf"],
            retrievers=tuple(entry["retrievers"]),
            ranks=dict(entry["ranks"]),
            signals=dict(entry["signals"]),
        )
        for chunk_id, entry in ordered
    )


def _record_signal(signals: dict[str, float], retriever: str, score: float) -> None:
    name = RETRIEVER_SIGNALS.get(retriever)
    if name is None:
        return
    signals[name] = max(signals.get(name, 0.0), float(score))
