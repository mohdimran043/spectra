"""Contradiction radar: find real disagreements, explain them, adjudicate them.

Detection is mechanical (attribute conflicts, negation polarity, impossible
ordering) - a model is never asked whether two sources disagree.  Resolution is
also mechanical: version status, recency, reliability and specificity decide,
and the losing evidence stays in the ledger with the reason it lost.  A model may
only be used to *phrase* an explanation that was already computed.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations

from spectra_ai_core.interfaces import ChatMessage
from spectra_config.logging import get_logger
from spectra_schemas import Contradiction, EvidenceItem, ModelRole

from .lexicons import (
    ATTRIBUTE_LEXICON,
    COMPATIBLE_VALUES,
    EXCLUSIVE_ATTRIBUTES,
    NUMERIC_ATTRIBUTES,
    NUMERIC_RELATIVE_TOLERANCE,
    PRECEDENCE_RULES,
    TEMPORAL_TOLERANCE_SECONDS,
)
from .reliability import ReliabilityScorer
from .text_utils import matched_terms, truncate
from .triples import AttributeClaim, Lexicon, extract_claims

log = get_logger(__name__)

KIND_VALUE_CONFLICT = "value_conflict"
KIND_POLARITY_CONFLICT = "polarity_conflict"
KIND_TEMPORAL_IMPOSSIBILITY = "temporal_impossibility"

# Base severity per kind.  A direct denial of the same predicate is worse than
# two different values (which can be a stale copy); an impossible ordering is
# worst because it invalidates the causal chain an investigation is built on.
BASE_SEVERITY: Mapping[str, float] = {
    KIND_VALUE_CONFLICT: 0.60,
    KIND_POLARITY_CONFLICT: 0.70,
    KIND_TEMPORAL_IMPOSSIBILITY: 0.80,
}
# A conflict between two strong items matters more than one between two weak
# ones, so the weaker item's weight adds up to this much severity.
SEVERITY_WEIGHT_BONUS = 0.20

# Adjudication weights.  Version status leads because "superseded" is an explicit
# statement by the system of record that a document no longer applies.
RESOLUTION_WEIGHTS: Mapping[str, float] = {
    "version_status": 0.35,
    "recency": 0.25,
    "reliability": 0.25,
    "specificity": 0.15,
}
# Beyond a month apart, the older record is treated as fully stale; inside it,
# recency degrades smoothly so a few hours never decides an investigation.
RECENCY_SATURATION_DAYS = 30.0
# Below this margin the two sides are too close to call and both stand.
MIN_DECISION_MARGIN = 0.05
# Evidence that does not name the entity is weaker but not worthless.
SPECIFICITY_WITHOUT_ENTITY = 0.5
MAX_DETAIL_CHARS = 320
MAX_PHRASE_CHARS = 600
SECONDS_PER_DAY = 86_400.0


@dataclass(frozen=True)
class _Adjudication:
    score_a: float
    score_b: float
    reasons: tuple[str, ...]
    decisive: str | None = None


class ContradictionRadar:
    """Detects, explains and resolves contradictions between evidence items."""

    def __init__(
        self,
        *,
        scorer: ReliabilityScorer | None = None,
        lexicon: Lexicon = ATTRIBUTE_LEXICON,
        precedence_rules: Sequence[tuple[tuple[str, str], tuple[str, str]]] = PRECEDENCE_RULES,
        temporal_tolerance_seconds: float = TEMPORAL_TOLERANCE_SECONDS,
    ) -> None:
        self._scorer = scorer or ReliabilityScorer()
        self._lexicon = lexicon
        self._rules = tuple(precedence_rules)
        self._tolerance = float(temporal_tolerance_seconds)

    # -- detection --------------------------------------------------------
    def detect(
        self, evidence: Sequence[EvidenceItem], entity_ids: Sequence[str] = ()
    ) -> list[Contradiction]:
        """Find every genuine disagreement between these evidence items."""
        items = {item.evidence_id: item for item in evidence}
        claims_by_key: dict[tuple[str, str], list[AttributeClaim]] = {}
        claims_by_item: dict[str, list[AttributeClaim]] = {}
        for item in evidence:
            claims = extract_claims(item, entity_ids, lexicon=self._lexicon)
            claims_by_item[item.evidence_id] = claims
            for claim in claims:
                claims_by_key.setdefault(claim.key(), []).append(claim)

        found: dict[str, Contradiction] = {}
        for claims in claims_by_key.values():
            for left, right in combinations(claims, 2):
                contradiction = self._compare(left, right, items)
                if contradiction:
                    _keep_strongest(found, contradiction)
        for contradiction in self._temporal_conflicts(claims_by_item, items):
            _keep_strongest(found, contradiction)
        results = sorted(found.values(), key=lambda c: (-c.severity, c.contradiction_id))
        log.info("contradiction.detected", count=len(results), evidence=len(evidence))
        return results

    def _compare(
        self, left: AttributeClaim, right: AttributeClaim, items: Mapping[str, EvidenceItem]
    ) -> Contradiction | None:
        if left.evidence_id == right.evidence_id:
            return None
        same_value = _same_value(left, right)
        if same_value and left.negated != right.negated:
            asserted, denied = (right, left) if left.negated else (left, right)
            statement = (
                f"{asserted.entity} is reported as {asserted.attribute} "
                f"'{asserted.value}' and as NOT {asserted.value}"
            )
            return self._build(KIND_POLARITY_CONFLICT, asserted, denied, statement, items)
        if same_value or left.negated or right.negated:
            return None
        if left.attribute not in EXCLUSIVE_ATTRIBUTES and left.attribute not in NUMERIC_ATTRIBUTES:
            return None
        if _are_compatible(left.attribute, left.value, right.value):
            return None
        statement = (
            f"{left.entity} {left.attribute} is reported as both "
            f"'{left.value}' and '{right.value}'"
        )
        return self._build(KIND_VALUE_CONFLICT, left, right, statement, items)

    def _temporal_conflicts(
        self,
        claims_by_item: Mapping[str, Sequence[AttributeClaim]],
        items: Mapping[str, EvidenceItem],
    ) -> list[Contradiction]:
        """An event recorded before the event that must precede it."""
        dated = [
            (claim, items[evidence_id].occurred_at)
            for evidence_id, claims in claims_by_item.items()
            for claim in claims
            if items.get(evidence_id) is not None and items[evidence_id].occurred_at is not None
        ]
        results: list[Contradiction] = []
        for earlier_marker, later_marker in self._rules:
            firsts = [pair for pair in dated if _matches(pair[0], earlier_marker)]
            seconds = [pair for pair in dated if _matches(pair[0], later_marker)]
            results.extend(self._temporal_pairs(firsts, seconds, items))
        return results

    def _temporal_pairs(
        self,
        firsts: Sequence[tuple[AttributeClaim, datetime]],
        seconds: Sequence[tuple[AttributeClaim, datetime]],
        items: Mapping[str, EvidenceItem],
    ) -> list[Contradiction]:
        results: list[Contradiction] = []
        for first, first_at in firsts:
            for second, second_at in seconds:
                if first.entity != second.entity or first.evidence_id == second.evidence_id:
                    continue
                gap = (_as_utc(first_at) - _as_utc(second_at)).total_seconds()
                if gap <= self._tolerance:
                    continue
                statement = (
                    f"{second.entity} is recorded as {second.attribute} '{second.value}' at "
                    f"{_stamp(second_at)}, before it was {first.attribute} '{first.value}' at "
                    f"{_stamp(first_at)}"
                )
                results.append(
                    self._build(KIND_TEMPORAL_IMPOSSIBILITY, second, first, statement, items)
                )
        return results

    def _build(
        self,
        kind: str,
        left: AttributeClaim,
        right: AttributeClaim,
        statement: str,
        items: Mapping[str, EvidenceItem],
    ) -> Contradiction:
        item_a, item_b = items.get(left.evidence_id), items.get(right.evidence_id)
        weights = [item.weight for item in (item_a, item_b) if item is not None]
        severity = BASE_SEVERITY[kind] + SEVERITY_WEIGHT_BONUS * (min(weights) if weights else 0.0)
        pair = "\x1f".join(sorted((left.evidence_id, right.evidence_id)))
        digest = hashlib.sha256(f"{kind}\x1f{pair}\x1f{left.entity}\x1f{left.attribute}".encode()).hexdigest()
        detail = " | ".join(
            f"{item.citation()}: \"{truncate(claim.sentence, MAX_DETAIL_CHARS)}\""
            for claim, item in ((left, item_a), (right, item_b))
            if item is not None
        )
        return Contradiction(
            contradiction_id=f"con_{digest[:12]}",
            statement=statement,
            evidence_a=left.evidence_id,
            evidence_b=right.evidence_id,
            kind=kind,
            detail=detail,
            severity=round(min(severity, 1.0), 4),
            entity_id=left.entity,
        )

    # -- explanation ------------------------------------------------------
    def explain(
        self, contradiction: Contradiction, evidence_by_id: Mapping[str, EvidenceItem]
    ) -> str:
        """Deterministic, citation-first explanation of the disagreement."""
        lines = [f"{contradiction.statement} (severity {contradiction.severity:.2f})."]
        for label, evidence_id in (("A", contradiction.evidence_a), ("B", contradiction.evidence_b)):
            item = evidence_by_id.get(evidence_id)
            if item is None:
                lines.append(f"{label}: {evidence_id} is no longer in the ledger.")
                continue
            lines.append(
                f"{label}: {item.citation()} - \"{truncate(item.summary, MAX_DETAIL_CHARS)}\" "
                f"[reliability {item.reliability:.2f}, {item.reliability_reason}]"
            )
        if contradiction.resolution:
            lines.append(f"Resolution: {contradiction.resolution}")
        return "\n".join(lines)

    async def phrase(
        self,
        contradiction: Contradiction,
        evidence_by_id: Mapping[str, EvidenceItem],
        *,
        gateway: object | None = None,
    ) -> str:
        """Optionally let a model rewrite the explanation - never decide it."""
        grounded = self.explain(contradiction, evidence_by_id)
        if gateway is None:
            return grounded
        prompt = (
            "Rewrite the following contradiction report as two plain sentences for an "
            "investigator. Do not add facts, do not resolve it, keep every citation.\n\n"
            f"{grounded}"
        )
        try:
            result = await gateway.generate(  # type: ignore[attr-defined]
                [ChatMessage(role="user", content=prompt)],
                role=ModelRole.FAST_BRAIN,
                max_tokens=256,
            )
            text = (getattr(result, "text", "") or "").strip()
        except Exception as exc:
            log.warning("contradiction.phrase_failed", error=str(exc))
            return grounded
        if not text or len(text) > MAX_PHRASE_CHARS:
            return grounded
        return text

    # -- resolution -------------------------------------------------------
    def resolve(
        self,
        contradiction: Contradiction,
        evidence_by_id: Mapping[str, EvidenceItem],
        *,
        now: datetime | None = None,
    ) -> Contradiction:
        """Adjudicate and return a NEW contradiction carrying the verdict."""
        item_a = evidence_by_id.get(contradiction.evidence_a)
        item_b = evidence_by_id.get(contradiction.evidence_b)
        if item_a is None or item_b is None:
            return contradiction.model_copy(
                update={
                    "resolution": "Cannot adjudicate: one side is missing from the ledger.",
                    "resolved_in_favour_of": None,
                }
            )
        verdict = self._adjudicate(item_a, item_b, contradiction.entity_id)
        margin = abs(verdict.score_a - verdict.score_b)
        if verdict.decisive is None and margin < MIN_DECISION_MARGIN:
            reason = "; ".join(verdict.reasons) or "no distinguishing signal"
            return contradiction.model_copy(
                update={
                    "resolution": (
                        f"Unresolved: the two sources are too close to call "
                        f"({verdict.score_a:.2f} vs {verdict.score_b:.2f}; {reason}). Both stand."
                    ),
                    "resolved_in_favour_of": None,
                }
            )
        winner = verdict.decisive or (
            contradiction.evidence_a if verdict.score_a > verdict.score_b else contradiction.evidence_b
        )
        loser = contradiction.evidence_b if winner == contradiction.evidence_a else contradiction.evidence_a
        reason = "; ".join(verdict.reasons) or "higher overall adjudication score"
        return contradiction.model_copy(
            update={
                "resolution": (
                    f"Resolved in favour of {winner} over {loser}: {reason} "
                    f"(score {max(verdict.score_a, verdict.score_b):.2f} vs "
                    f"{min(verdict.score_a, verdict.score_b):.2f})."
                ),
                "resolved_in_favour_of": winner,
            }
        )

    def _adjudicate(
        self, item_a: EvidenceItem, item_b: EvidenceItem, entity_id: str | None
    ) -> _Adjudication:
        version_a = self._scorer.version_score(item_a.provenance.version_status)
        version_b = self._scorer.version_score(item_b.provenance.version_status)
        recency_a, recency_b = _recency_scores(item_a, item_b)
        specificity_a = _specificity(item_a, entity_id)
        specificity_b = _specificity(item_b, entity_id)
        parts_a = {
            "version_status": version_a,
            "recency": recency_a,
            "reliability": item_a.reliability,
            "specificity": specificity_a,
        }
        parts_b = {
            "version_status": version_b,
            "recency": recency_b,
            "reliability": item_b.reliability,
            "specificity": specificity_b,
        }
        score_a = sum(RESOLUTION_WEIGHTS[name] * value for name, value in parts_a.items())
        score_b = sum(RESOLUTION_WEIGHTS[name] * value for name, value in parts_b.items())
        decisive, reasons = _superseded_rule(item_a, item_b)
        reasons.extend(_component_reasons(item_a, item_b, parts_a, parts_b))
        return _Adjudication(round(score_a, 4), round(score_b, 4), tuple(reasons), decisive)


def _superseded_rule(item_a: EvidenceItem, item_b: EvidenceItem) -> tuple[str | None, list[str]]:
    """A superseded version cannot win against a live one - a hard rule."""
    a_superseded = _is_superseded(item_a)
    b_superseded = _is_superseded(item_b)
    if a_superseded == b_superseded:
        return None, []
    winner = item_b if a_superseded else item_a
    loser = item_a if a_superseded else item_b
    winner_status = (winner.provenance.version_status or "unknown").strip().lower()
    return winner.evidence_id, [
        f"{loser.evidence_id} is marked superseded while {winner.evidence_id} is {winner_status}"
    ]


def _component_reasons(
    item_a: EvidenceItem,
    item_b: EvidenceItem,
    parts_a: Mapping[str, float],
    parts_b: Mapping[str, float],
) -> list[str]:
    """Name the components that actually separated the two sides."""
    phrases = {
        "version_status": lambda win, lose: (
            f"version status '{win.provenance.version_status}' beats '{lose.provenance.version_status}'"
        ),
        "recency": lambda win, lose: f"{win.evidence_id} is the more recent record",
        "reliability": lambda win, lose: (
            f"reliability {win.reliability:.2f} vs {lose.reliability:.2f}"
        ),
        "specificity": lambda win, lose: f"{win.evidence_id} names the entity explicitly",
    }
    reasons: list[str] = []
    for name, weight in RESOLUTION_WEIGHTS.items():
        delta = (parts_a[name] - parts_b[name]) * weight
        if abs(delta) < 0.01:
            continue
        win, lose = (item_a, item_b) if delta > 0 else (item_b, item_a)
        reasons.append(phrases[name](win, lose))
    return reasons


def _is_superseded(item: EvidenceItem) -> bool:
    return (item.provenance.version_status or "").strip().lower() == "superseded"


def _recency_scores(item_a: EvidenceItem, item_b: EvidenceItem) -> tuple[float, float]:
    stamp_a, stamp_b = _record_time(item_a), _record_time(item_b)
    if stamp_a is None and stamp_b is None:
        return 0.5, 0.5
    if stamp_a is None:
        return 0.0, 1.0
    if stamp_b is None:
        return 1.0, 0.0
    gap_days = abs((stamp_a - stamp_b).total_seconds()) / SECONDS_PER_DAY
    older = max(0.0, 1.0 - min(gap_days / RECENCY_SATURATION_DAYS, 1.0))
    return (1.0, older) if stamp_a >= stamp_b else (older, 1.0)


def _record_time(item: EvidenceItem) -> datetime | None:
    stamp = item.provenance.modified_at or item.occurred_at or item.provenance.created_at
    return _as_utc(stamp) if stamp else None


def _specificity(item: EvidenceItem, entity_id: str | None) -> float:
    if not entity_id:
        return 1.0
    if entity_id in item.entities or matched_terms(f"{item.summary} {item.excerpt}", [entity_id]):
        return 1.0
    return SPECIFICITY_WITHOUT_ENTITY


def _are_compatible(attribute: str, left_value: str, right_value: str) -> bool:
    """True when two different values are just two wordings of one situation."""
    return any(
        {left_value, right_value} <= group for group in COMPATIBLE_VALUES.get(attribute, ())
    )


def _same_value(left: AttributeClaim, right: AttributeClaim) -> bool:
    if left.numeric is not None and right.numeric is not None:
        scale = max(abs(left.numeric), abs(right.numeric), 1.0)
        return abs(left.numeric - right.numeric) / scale <= NUMERIC_RELATIVE_TOLERANCE
    return left.value == right.value


def _matches(claim: AttributeClaim, marker: tuple[str, str]) -> bool:
    return not claim.negated and claim.attribute == marker[0] and claim.value == marker[1]


def _keep_strongest(found: dict[str, Contradiction], contradiction: Contradiction) -> None:
    current = found.get(contradiction.contradiction_id)
    if current is None or contradiction.severity > current.severity:
        found[contradiction.contradiction_id] = contradiction


def _stamp(value: datetime) -> str:
    return _as_utc(value).strftime("%Y-%m-%d %H:%M:%S")


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


__all__ = [
    "KIND_POLARITY_CONFLICT",
    "KIND_TEMPORAL_IMPOSSIBILITY",
    "KIND_VALUE_CONFLICT",
    "MIN_DECISION_MARGIN",
    "RESOLUTION_WEIGHTS",
    "ContradictionRadar",
]
