"""Deciding whether a piece of evidence supports or conflicts with a claim.

Stance is assigned by a deterministic reading of the evidence text against the
claim: the item must talk about the same subject at all, and then either name a
competing outcome (contradicting) or restate the claim's own terms (supporting).
Anything else stays NEUTRAL - an honest "this is related but decides nothing".
"""

from __future__ import annotations

from spectra_schemas import EvidenceItem, EvidenceStance

# The causal lexicon belongs to the Hypothesis Engine, but stance is not that
# agent's: the Brain stances its supporting evidence, the Disproof Agent stances
# what it finds, and the Verifier reads the result.  It therefore stays a
# package-root primitive rather than moving into any one agent's package.
from .agents.hypothesis.causal_lexicon import competing_outcomes, negate, salient_terms

# An item must share at least one salient term with the claim before its stance
# means anything; otherwise it is simply about something else.
MIN_SUBJECT_OVERLAP = 1
# Restating half the claim's salient terms is what makes an item supporting
# rather than merely topical.
SUPPORT_TERM_RATIO = 0.5


def item_text(item: EvidenceItem) -> str:
    return f"{item.summary} {item.excerpt} {' '.join(item.entities)}".lower()


def classify(claim: str, item: EvidenceItem) -> EvidenceStance:
    """Stance of ``item`` with respect to ``claim``."""
    text = item_text(item)
    claim_terms = salient_terms(claim)
    if not claim_terms:
        return EvidenceStance.NEUTRAL
    overlap = [term for term in claim_terms if term in text]
    if len(overlap) < MIN_SUBJECT_OVERLAP:
        return EvidenceStance.NEUTRAL

    counters = set(competing_outcomes(claim)) | {phrase for phrase in negate(claim)}
    if any(counter in text for counter in counters if counter):
        return EvidenceStance.CONTRADICTING
    if len(overlap) >= max(2, int(len(claim_terms) * SUPPORT_TERM_RATIO)):
        return EvidenceStance.SUPPORTING
    return EvidenceStance.NEUTRAL


def restance(item: EvidenceItem, stance: EvidenceStance) -> EvidenceItem:
    """Immutable stance update."""
    if item.stance is stance:
        return item
    return item.model_copy(update={"stance": stance})
