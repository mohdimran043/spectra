"""Resolution, evidence, reasoning and calibration metrics."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from ..datasets.benchmark import Target

CITATION_PATTERN = re.compile(r"\[E(\d+)\]")
# A sentence with no verb-bearing content is a heading, not an assertion.
MIN_ASSERTION_WORDS = 4


@dataclass(frozen=True)
class PRF:
    precision: float
    recall: float
    f1: float

    @classmethod
    def from_counts(cls, true_positive: int, false_positive: int, false_negative: int) -> PRF:
        precision = true_positive / (true_positive + false_positive) if (true_positive + false_positive) else 0.0
        recall = true_positive / (true_positive + false_negative) if (true_positive + false_negative) else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        return cls(round(precision, 6), round(recall, 6), round(f1, 6))


def _normalise(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(value)).upper()


def entity_resolution_prf(produced: Sequence[str], expected: Sequence[str]) -> PRF:
    """Precision/recall/F1 over resolved entity identifiers."""
    got = {_normalise(v) for v in produced if str(v).strip()}
    want = {_normalise(v) for v in expected if str(v).strip()}
    if not want:
        return PRF(1.0, 1.0, 1.0) if not got else PRF(0.0, 1.0, 0.0)
    true_positive = len(got & want)
    return PRF.from_counts(true_positive, len(got - want), len(want - got))


def evidence_completeness(produced: Sequence[Target], expected: Sequence[Target]) -> float:
    """Fraction of the expected citations the answer actually produced."""
    if not expected:
        return 1.0
    satisfied = sum(1 for want in expected if any(want.matches(got) for got in produced))
    return round(satisfied / len(expected), 6)


def claim_support(answer: str, evidence_labels: Sequence[str]) -> float:
    """Fraction of asserted sentences carrying a citation that actually exists.

    An answer that cites `[E9]` when only three evidence items were returned is
    penalised exactly as hard as one that cites nothing.
    """
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", answer or "") if s.strip()]
    assertions = [s for s in sentences if len(s.split()) >= MIN_ASSERTION_WORDS]
    if not assertions:
        return 0.0
    valid = {str(label).upper().lstrip("E") for label in evidence_labels}
    supported = 0
    for sentence in assertions:
        cited = CITATION_PATTERN.findall(sentence)
        if cited and all(number in valid for number in cited):
            supported += 1
    return round(supported / len(assertions), 6)


def contradiction_prf(detected: int, expected: int, false_positives: int = 0) -> PRF:
    true_positive = min(detected, expected)
    return PRF.from_counts(true_positive, false_positives + max(detected - expected, 0),
                           max(expected - detected, 0))


def investigation_success(
    produced_status: str, expected_status: str, produced_answer: str, expected_conclusion: str
) -> float:
    """Status must match; the conclusion is scored by key-term overlap.

    Exact string match on a free-text conclusion would measure phrasing, not
    correctness, so the conclusion is checked on its distinctive terms instead.
    """
    if produced_status != expected_status:
        return 0.0
    if not expected_conclusion.strip():
        return 1.0
    return round(0.5 + 0.5 * term_overlap(produced_answer, expected_conclusion), 6)


STOPWORDS = frozenset(
    """a an the was were is are be been being of to in on at by for with from that this it its
    not no and or but so because therefore which who whom whose when where how what why did does
    do had has have as if then than there their they them he she his her our your my""".split()
)


def _terms(text: str) -> set[str]:
    words = re.findall(r"[A-Za-z0-9_]+", (text or "").lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 2}


def term_overlap(produced: str, expected: str) -> float:
    """Share of the expected conclusion's distinctive terms that appear."""
    want = _terms(expected)
    if not want:
        return 1.0
    got = _terms(produced)
    return round(len(want & got) / len(want), 6)


def abstention_outcome(produced_status: str, expected_status: str) -> str:
    """Classify calibration: the dangerous case is answering when you shouldn't."""
    should_abstain = expected_status == "insufficient_evidence"
    did_abstain = produced_status in {"insufficient_evidence", "degraded"}
    if should_abstain and did_abstain:
        return "correctly_abstained"
    if should_abstain and not did_abstain:
        return "wrongly_answered"
    if not should_abstain and did_abstain:
        return "wrongly_abstained"
    return "correctly_answered"


def percentiles(values: Sequence[float]) -> dict[str, float]:
    if not values:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "mean": 0.0, "max": 0.0}
    ordered = sorted(values)

    def at(pct: float) -> float:
        index = min(int(round(pct / 100 * (len(ordered) - 1))), len(ordered) - 1)
        return round(ordered[index], 3)

    return {
        "p50": at(50),
        "p95": at(95),
        "p99": at(99),
        "mean": round(sum(ordered) / len(ordered), 3),
        "max": round(ordered[-1], 3),
    }
