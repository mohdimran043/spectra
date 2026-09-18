"""Deciding what the answer is allowed to claim.

Status and confidence are derived from the evidence, the verification result
and the contradictions - never from the fluency of the generated text.
"""

from __future__ import annotations

from collections.abc import Sequence

from spectra_schemas import AnswerStatus, Claim, InvestigationState

from . import sufficiency

# Confidence when nothing was verified and no claims survived: half the
# sufficiency score, i.e. "there is evidence, but nothing was corroborated".
UNVERIFIED_DAMPING = 0.5


def answer_status(state: InvestigationState, score: float, threshold: float) -> AnswerStatus:
    intent = state.understanding.intent if state.understanding else None
    authoritative = sufficiency.authoritative_item(state.evidence, intent)
    if not state.evidence.items or (score < threshold and authoritative is None):
        return AnswerStatus.INSUFFICIENT_EVIDENCE
    if any(c.resolution is None for c in state.contradictions):
        return AnswerStatus.CONTESTED
    if state.verification is not None and state.verification.supported:
        return AnswerStatus.SUPPORTED
    if state.degraded:
        return AnswerStatus.DEGRADED
    return AnswerStatus.PARTIALLY_SUPPORTED


def confidence_for(
    state: InvestigationState, claims: Sequence[Claim], score: float, status: AnswerStatus
) -> float:
    if status is AnswerStatus.INSUFFICIENT_EVIDENCE:
        return round(score, 4)
    intent = state.understanding.intent if state.understanding else None
    authoritative = sufficiency.authoritative_item(state.evidence, intent)
    if authoritative is not None and state.verification is None:
        # Confidence in an exact system-of-record match is that record's own weight.
        return round(authoritative.weight, 4)
    if state.verification is not None:
        return round(state.verification.confidence, 4)
    if not claims:
        return round(score * UNVERIFIED_DAMPING, 4)
    return round(sum(c.confidence for c in claims) / len(claims) * score, 4)


def followups(state: InvestigationState) -> list[str]:
    """Concrete next questions, derived from the gaps this run could not close."""
    suggestions: list[str] = []
    for gap in sufficiency.gaps(state.evidence)[:2]:
        suggestions.append(f"Broaden the search to close this gap: {gap}")
    leader = state.leading_hypothesis()
    if leader is not None and leader.disproof_probe:
        suggestions.append(f"Test {leader.hypothesis_id} directly: {leader.disproof_probe}")
    for entry in state.agent_availability:
        if not entry.ready and entry.alternatives:
            suggestions.append(
                f"Re-run with {entry.name} enabled to cover {', '.join(entry.alternatives[:2])}"
            )
            break
    return suggestions[:4]
