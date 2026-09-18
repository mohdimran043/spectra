"""Confidence and status for one claim, from that claim's own evidence only.

This module is the point of the claim-centric design.  Confidence here is NOT a
probability shared out between rival explanations: nothing is normalised,
nothing has to sum to one, and adding a second claim never lowers the first.  A
finding that three independent sources corroborate scores as a finding that
three independent sources corroborate - whether it was the only statement the
evidence carried or one of six.  The previous design divided one probability
mass across every competing candidate, so a well-evidenced conclusion listed
beside six alternatives peaked around 0.16 and could never be reported as
confident.  That failure is structural, and removing the division is the fix.

    confidence = quality x corroboration x (1 - contradiction penalty)

* **quality** - mean weight (relevance x reliability) of the strongest
  supporting items, so a long tail of weak corroboration cannot inflate a claim
  and cannot dilute one that two strong items back;
* **corroboration** - a floored blend of how many items back the claim, how many
  independent sources they come from, and how diverse those sources are;
* **contradiction penalty** - the share of the claim's total evidence weight
  that points the other way.

Status follows the balance of weight rather than the confidence number, so a
claim with real counter-evidence is reported as contradicted even when the
supporting side is individually strong.
"""

from __future__ import annotations

from collections.abc import Sequence

from spectra_schemas import (
    Claim,
    ClaimStatus,
    EvidenceItem,
    EvidenceLedger,
    EvidenceStance,
)

from ...thresholds import (
    CLAIM_COUNT_WEIGHT,
    CLAIM_DIVERSITY_WEIGHT,
    CLAIM_QUALITY_SAMPLE,
    CLAIM_SOURCE_WEIGHT,
    CLAIM_SUPPORTED_MIN,
    CONTRADICTED_WEIGHT_RATIO,
    CORROBORATION_FLOOR,
    MIN_CONTRADICTING_FOR_REFUTED,
    MIN_INDEPENDENT_SOURCES,
    MIN_SUPPORTING_ITEMS,
    REFUTED_WEIGHT_RATIO,
)


def score_claim(claim: Claim, ledger: EvidenceLedger) -> Claim:
    """Re-score ``claim`` against ``ledger`` - returns a NEW claim."""
    support, contra = resolve(claim, ledger)
    confidence = confidence_for(support, contra)
    return claim.model_copy(
        update={
            "confidence": confidence,
            "status": status_for(confidence, support, contra),
            "supporting_evidence": [item.evidence_id for item in support],
            "contradicting_evidence": [item.evidence_id for item in contra],
        }
    )


def resolve(claim: Claim, ledger: EvidenceLedger) -> tuple[list[EvidenceItem], list[EvidenceItem]]:
    """The claim's supporting and contradicting items, as they stand in the ledger.

    Ids the claim already carries come first; anything the ledger itself links
    back to this claim - the disproof probe tags its finds that way - is folded
    in, so a probe result counts even if the claim was not re-attached.
    """
    by_id = {item.evidence_id: item for item in ledger.items}
    support_ids = list(claim.supporting_evidence)
    contra_ids = list(claim.contradicting_evidence)
    for item in ledger.items:
        if claim.claim_id not in item.claim_ids:
            continue
        if item.stance is EvidenceStance.CONTRADICTING and item.evidence_id not in contra_ids:
            contra_ids.append(item.evidence_id)
        elif item.stance is EvidenceStance.SUPPORTING and item.evidence_id not in support_ids:
            support_ids.append(item.evidence_id)
    contested = set(contra_ids)
    support = [by_id[i] for i in support_ids if i in by_id and i not in contested]
    contra = [by_id[i] for i in contra_ids if i in by_id]
    return _heaviest_first(support), _heaviest_first(contra)


def confidence_for(support: Sequence[EvidenceItem], contra: Sequence[EvidenceItem]) -> float:
    """Confidence in [0, 1] from this claim's evidence, normalised against nothing."""
    if not support:
        return 0.0
    quality = _quality(support)
    penalty = _contradiction_penalty(support, contra)
    return _clamp(quality * _corroboration(support) * (1.0 - penalty))


def status_for(
    confidence: float, support: Sequence[EvidenceItem], contra: Sequence[EvidenceItem]
) -> ClaimStatus:
    """Where the claim sits on the evidence, by the balance of weight."""
    support_weight = _total_weight(support)
    contra_weight = _total_weight(contra)
    if not support and not contra:
        return ClaimStatus.INSUFFICIENT
    if (
        len(contra) >= MIN_CONTRADICTING_FOR_REFUTED
        and contra_weight >= REFUTED_WEIGHT_RATIO * support_weight
    ):
        return ClaimStatus.REFUTED
    if contra and contra_weight >= CONTRADICTED_WEIGHT_RATIO * support_weight:
        return ClaimStatus.CONTRADICTED
    if not support:
        return ClaimStatus.INSUFFICIENT
    if confidence >= CLAIM_SUPPORTED_MIN and len(support) >= MIN_SUPPORTING_ITEMS:
        return ClaimStatus.SUPPORTED
    return ClaimStatus.WEAK


def rationale_for(claim: Claim, support: Sequence[EvidenceItem], contra: Sequence[EvidenceItem]) -> str:
    """One line an analyst can audit: what backs this claim and what fights it."""
    sources = {item.provenance.source_id for item in support}
    parts = [
        f"{len(support)} supporting item(s) from {len(sources)} independent source(s), "
        f"weight {_total_weight(support):.2f}"
    ]
    if contra:
        parts.append(f"{len(contra)} conflicting item(s), weight {_total_weight(contra):.2f}")
    if claim.rationale:
        parts.insert(0, claim.rationale)
    return "; ".join(parts)


# -- terms ----------------------------------------------------------------
def _quality(support: Sequence[EvidenceItem]) -> float:
    sample = list(support)[:CLAIM_QUALITY_SAMPLE]
    return sum(item.weight for item in sample) / len(sample)


def _corroboration(support: Sequence[EvidenceItem]) -> float:
    count_term = min(len(support) / MIN_SUPPORTING_ITEMS, 1.0)
    sources = {item.provenance.source_id for item in support}
    source_term = min(len(sources) / MIN_INDEPENDENT_SOURCES, 1.0)
    diversity_term = EvidenceLedger(items=list(support)).diversity()
    blend = (
        CLAIM_COUNT_WEIGHT * count_term
        + CLAIM_SOURCE_WEIGHT * source_term
        + CLAIM_DIVERSITY_WEIGHT * diversity_term
    )
    return CORROBORATION_FLOOR + (1.0 - CORROBORATION_FLOOR) * blend


def _contradiction_penalty(
    support: Sequence[EvidenceItem], contra: Sequence[EvidenceItem]
) -> float:
    contra_weight = _total_weight(contra)
    if contra_weight <= 0.0:
        return 0.0
    return contra_weight / (_total_weight(support) + contra_weight)


def _total_weight(items: Sequence[EvidenceItem]) -> float:
    return sum(item.weight for item in items)


def _heaviest_first(items: Sequence[EvidenceItem]) -> list[EvidenceItem]:
    return sorted(items, key=lambda item: item.weight, reverse=True)


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)
