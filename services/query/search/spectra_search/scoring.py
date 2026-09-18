"""Unified relevance scoring.

Ranking is a *weighted, normalised combination of named signals*, never a raw
cosine.  Every number that reaches the UI can be traced back to a signal, a
weight and a normalisation - which is what makes the Search Autopsy screen
possible and what stops "the vector said so" from being an explanation.

Signals
-------
``lexical``            BM25 evidence that the query's words are in the chunk
``semantic``           dense / multimodal ANN similarity
``rerank``             cross-encoder score for the candidates that earned one
``entity_match``       the chunk carries an enterprise id the query named
``metadata_match``     how many of the request's filter facets the chunk matches
``source_reliability`` how much the source of record is trusted
``freshness``          exponential decay on the event date
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from spectra_schemas import Chunk, ScoreBreakdown, SearchFilters, SearchHit, SourceDescriptor, SourceType

from .candidates import FusedCandidate

# ---------------------------------------------------------------------------
# Weights.  They sum to 1.0 so a normalised score lands in [0, 1] before the
# exact-id bonus.  The split encodes the retrieval literature's consensus and
# this system's priorities: the cross-encoder is the single best relevance
# signal available (0.30), lexical and dense evidence are complementary and
# roughly equal (0.22 / 0.24), and the enterprise-specific signals correct the
# ranking rather than drive it.
# ---------------------------------------------------------------------------
WEIGHT_LEXICAL = 0.22
WEIGHT_SEMANTIC = 0.24
WEIGHT_RERANK = 0.30
WEIGHT_ENTITY_MATCH = 0.12
WEIGHT_METADATA_MATCH = 0.04
WEIGHT_SOURCE_RELIABILITY = 0.05
WEIGHT_FRESHNESS = 0.03

# An exact enterprise-id match is categorical, not gradual: in an investigation a
# chunk that literally contains TX82931 is always more relevant than one that
# merely resembles the query.  The bonus therefore equals the maximum achievable
# weighted base (1.0), which makes exact hits a strict tier above everything else
# while preserving full ranking *within* each tier.  Final scores live in [0, 2].
EXACT_ID_BONUS = 1.0

# Half-life of the freshness decay: 180 days is one enterprise reporting cycle -
# a six-month-old document is worth half a fresh one, all else being equal.
FRESHNESS_HALF_LIFE_DAYS = 180.0

# ---------------------------------------------------------------------------
# Admissibility.  Every signal below is min-max normalised across the result
# set, which means the best candidate always scores 1.0 on its strongest signal
# however poor it is in absolute terms - so the scorer could never express
# "nothing matched" and a query for a name absent from the corpus came back with
# five confident-looking hits.  The gate therefore reads the RAW signals, before
# normalisation, and drops anything carrying no actual evidence.
#
# Measured on this corpus:
#   'imran' (absent)            lexical 0.0000   rerank 0.0067-0.2230
#   'authentication timeout'    lexical 1.7-4.9  rerank 0.7996-0.9753
#   'TX83155' (exact)           lexical 1.2-2.6  rerank 0.9408-0.9754
# ---------------------------------------------------------------------------

#: A cross-encoder score high enough to admit a candidate that shares no words
#: with the query - a true paraphrase.  Sits above the 0.223 ceiling measured
#: for a query with nothing to match.
MIN_RERANK_EVIDENCE = 0.35


def has_evidence(raw: Mapping[str, float | None], is_exact: bool) -> bool:
    """True when a candidate has some real reason to be in the result set.

    Cosine similarity is deliberately not sufficient on its own: an exact
    enterprise-id match measured 0.35-0.47 semantic while an absent query
    measured 0.30-0.42, so the signal cannot separate a match from noise.
    """
    if is_exact or (raw.get("entity_match") or 0.0) > 0.0:
        return True
    if (raw.get("lexical") or 0.0) > 0.0:
        return True
    rerank = raw.get("rerank")
    return rerank is not None and rerank >= MIN_RERANK_EVIDENCE


# Used for signals that are genuinely unknown (no date, no source record).  A
# neutral 0.5 neither rewards nor punishes missing metadata.
NEUTRAL_SIGNAL = 0.5

# Trust priors per source type.  A system of record is authoritative; an ad-hoc
# upload is not.  ``SourceDescriptor.reliability_override`` always wins.
DEFAULT_SOURCE_RELIABILITY = 0.70
SOURCE_TYPE_RELIABILITY: dict[SourceType, float] = {
    SourceType.POSTGRES: 0.95,
    SourceType.MYSQL: 0.95,
    SourceType.SQLITE: 0.90,
    SourceType.S3: 0.75,
    SourceType.LOCAL_FOLDER: 0.75,
    SourceType.REST_API: 0.70,
    SourceType.UPLOAD: 0.60,
}

SIGNAL_NAMES = (
    "lexical",
    "semantic",
    "rerank",
    "entity_match",
    "metadata_match",
    "source_reliability",
    "freshness",
)


@dataclass(frozen=True)
class ScoringWeights:
    """Per-signal weights.  Immutable; ``rebalanced`` returns a new instance."""

    lexical: float = WEIGHT_LEXICAL
    semantic: float = WEIGHT_SEMANTIC
    rerank: float = WEIGHT_RERANK
    entity_match: float = WEIGHT_ENTITY_MATCH
    metadata_match: float = WEIGHT_METADATA_MATCH
    source_reliability: float = WEIGHT_SOURCE_RELIABILITY
    freshness: float = WEIGHT_FRESHNESS

    def as_mapping(self) -> dict[str, float]:
        return {name: float(getattr(self, name)) for name in SIGNAL_NAMES}

    def without_rerank(self) -> ScoringWeights:
        """Redistribute the reranker's weight proportionally when it is unavailable."""
        remaining = sum(value for name, value in self.as_mapping().items() if name != "rerank")
        if remaining <= 0:
            return replace(self, rerank=0.0)
        factor = (remaining + self.rerank) / remaining
        scaled = {name: value * factor for name, value in self.as_mapping().items() if name != "rerank"}
        return replace(self, rerank=0.0, **scaled)

    @classmethod
    def from_settings(cls, settings: Any | None) -> ScoringWeights:
        """Read ``search_weight_<signal>`` overrides from settings when present."""
        if settings is None:
            return cls()
        overrides = {
            name: float(getattr(settings, f"search_weight_{name}"))
            for name in SIGNAL_NAMES
            if getattr(settings, f"search_weight_{name}", None) is not None
        }
        return cls(**overrides) if overrides else cls()


@dataclass(frozen=True)
class ScoreInput:
    """Everything the scorer needs about one candidate."""

    fused: FusedCandidate
    chunk: Chunk
    source: SourceDescriptor | None = None
    rerank: float | None = None


@dataclass(frozen=True)
class ScoredCandidate:
    chunk_id: str
    chunk: Chunk
    breakdown: ScoreBreakdown
    is_exact: bool
    retrievers: tuple[str, ...]


class UnifiedScorer:
    """Combine signals into one explainable score."""

    def __init__(
        self,
        weights: ScoringWeights | None = None,
        *,
        half_life_days: float = FRESHNESS_HALF_LIFE_DAYS,
        exact_bonus: float = EXACT_ID_BONUS,
    ) -> None:
        self._weights = weights or ScoringWeights()
        self._half_life_days = half_life_days
        self._exact_bonus = exact_bonus

    @property
    def weights(self) -> ScoringWeights:
        return self._weights

    def score(
        self,
        inputs: Sequence[ScoreInput],
        *,
        filters: SearchFilters | None = None,
        now: datetime | None = None,
        reranked: bool = True,
    ) -> tuple[ScoredCandidate, ...]:
        """Score every candidate, min-max normalising each signal across the set."""
        if not inputs:
            return ()
        moment = now or datetime.now(timezone.utc)
        scored_inputs = list(inputs)
        raw = [self._raw_signals(item, filters, moment) for item in scored_inputs]
        # Drop the evidence-free candidates BEFORE normalising, so the survivors
        # are rescaled against each other rather than against noise.
        admitted = [
            (item, values)
            for item, values in zip(scored_inputs, raw, strict=False)
            if has_evidence(values, item.fused.is_exact)
        ]
        if not admitted:
            return ()
        scored_inputs = [item for item, _ in admitted]
        normalised = _normalise_columns([values for _, values in admitted])
        weights = self._weights if reranked else self._weights.without_rerank()
        mapping = weights.as_mapping()
        scored = [
            self._build(item, values, mapping)
            for item, values in zip(scored_inputs, normalised, strict=False)
        ]
        return tuple(sorted(scored, key=lambda row: (-row.breakdown.final, row.chunk_id)))

    def explain(self, hit: SearchHit) -> str:
        """One human-readable sentence describing why ``hit`` ranks where it does."""
        weights = self._weights.as_mapping()
        breakdown = hit.scores
        contributions = [
            (name, getattr(breakdown, name) or 0.0, weights[name])
            for name in SIGNAL_NAMES
            if getattr(breakdown, name) is not None
        ]
        contributions.sort(key=lambda row: -(row[1] * row[2]))
        parts = [f"{name}={value:.2f}x{weight:.2f}" for name, value, weight in contributions if weight > 0]
        exact = " +exact-id bonus" if breakdown.entity_match >= 1.0 else ""
        return (
            f"{hit.chunk_id} scored {breakdown.final:.3f} from " + ", ".join(parts) + exact
            + f" (signals min-max normalised within this result set; source {hit.source_id})."
        )

    # -- internals --------------------------------------------------------
    def _raw_signals(
        self, item: ScoreInput, filters: SearchFilters | None, now: datetime
    ) -> dict[str, float | None]:
        signals = item.fused.signals
        return {
            "lexical": float(signals.get("lexical", 0.0)),
            "semantic": float(signals.get("semantic", 0.0)),
            "rerank": item.rerank,
            "entity_match": float(signals.get("entity_match", 0.0)),
            "metadata_match": metadata_match(item.chunk, filters),
            "source_reliability": source_reliability(item.source),
            "freshness": freshness(item.chunk, now, self._half_life_days),
        }

    def _build(
        self, item: ScoreInput, values: Mapping[str, float | None], weights: Mapping[str, float]
    ) -> ScoredCandidate:
        base = sum(weights[name] * (values[name] or 0.0) for name in SIGNAL_NAMES)
        is_exact = item.fused.is_exact
        final = base + (self._exact_bonus if is_exact else 0.0)
        breakdown = ScoreBreakdown(
            lexical=round(values["lexical"] or 0.0, 6),
            semantic=round(values["semantic"] or 0.0, 6),
            rerank=None if values["rerank"] is None else round(values["rerank"], 6),
            entity_match=round(values["entity_match"] or 0.0, 6),
            metadata_match=round(values["metadata_match"] or 0.0, 6),
            source_reliability=round(values["source_reliability"] or 0.0, 6),
            freshness=round(values["freshness"] or 0.0, 6),
            final=round(final, 6),
        )
        return ScoredCandidate(
            chunk_id=item.chunk.chunk_id,
            chunk=item.chunk,
            breakdown=breakdown,
            is_exact=is_exact,
            retrievers=item.fused.retrievers,
        )


def metadata_match(chunk: Chunk, filters: SearchFilters | None) -> float:
    """Fraction of the request's filter facets this chunk satisfies."""
    if filters is None or filters.is_empty():
        return NEUTRAL_SIGNAL
    facets: list[bool] = []
    if filters.modalities:
        facets.append(chunk.modality in filters.modalities)
    if filters.source_ids:
        facets.append(chunk.source_id in filters.source_ids)
    if filters.asset_ids:
        facets.append(chunk.asset_id in filters.asset_ids)
    if filters.entity_ids:
        facets.append(any(entity in filters.entity_ids for entity in chunk.entities))
    if filters.media_types:
        facets.append(str(chunk.metadata.get("media_type", "")) in filters.media_types)
    if filters.occurred_after or filters.occurred_before:
        facets.append(_within_window(chunk, filters))
    if not facets:
        return NEUTRAL_SIGNAL
    return sum(1 for matched in facets if matched) / len(facets)


def source_reliability(source: SourceDescriptor | None) -> float:
    if source is None:
        return DEFAULT_SOURCE_RELIABILITY
    if source.reliability_override is not None:
        return float(source.reliability_override)
    return SOURCE_TYPE_RELIABILITY.get(source.type, DEFAULT_SOURCE_RELIABILITY)


def freshness(chunk: Chunk, now: datetime, half_life_days: float) -> float:
    """Exponential decay ``0.5 ** (age / half_life)`` on the event date."""
    moment = chunk.occurred_at or chunk.created_at
    if moment is None or half_life_days <= 0:
        return NEUTRAL_SIGNAL
    aware = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - aware).total_seconds() / 86_400.0)
    return float(0.5 ** (age_days / half_life_days))


def _within_window(chunk: Chunk, filters: SearchFilters) -> bool:
    moment = chunk.occurred_at or chunk.created_at
    if moment is None:
        return False
    aware = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    if filters.occurred_after and aware < _aware(filters.occurred_after):
        return False
    if filters.occurred_before and aware > _aware(filters.occurred_before):
        return False
    return True


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _normalise_columns(rows: Sequence[Mapping[str, float | None]]) -> list[dict[str, float | None]]:
    """Min-max normalise each signal across the result set.

    A signal with zero spread carries no ranking information, so it collapses to
    1.0 when present and 0.0 when absent rather than amplifying float noise.
    """
    bounds: dict[str, tuple[float, float]] = {}
    for name in SIGNAL_NAMES:
        values = [row[name] for row in rows if row[name] is not None]
        bounds[name] = (min(values), max(values)) if values else (0.0, 0.0)
    return [
        {name: _scale(row[name], *bounds[name]) for name in SIGNAL_NAMES}
        for row in rows
    ]


def _scale(value: float | None, low: float, high: float) -> float | None:
    if value is None:
        return None
    if high - low <= 1e-12:
        return 1.0 if value > 0 else 0.0
    return (value - low) / (high - low)
