"""Is there enough evidence to answer?

Sufficiency blends how much evidence there is, how independent it is and how
good it is.  The Brain stops iterating when this crosses the configured
threshold, and abstains when it never does.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from spectra_schemas import EvidenceItem, EvidenceKind, EvidenceLedger, QueryIntent

from .thresholds import (
    MIN_EVIDENCE_RELEVANCE,
    MIN_INDEPENDENT_SOURCES,
    SUFFICIENCY_COUNT_WEIGHT,
    SUFFICIENCY_DIVERSITY_WEIGHT,
    SUFFICIENCY_QUALITY_WEIGHT,
    TARGET_EVIDENCE_COUNT,
)

# Quality is the mean weight of the strongest items - a long tail of weak items
# should not dilute a well-evidenced answer, nor inflate a thin one.
QUALITY_SAMPLE = TARGET_EVIDENCE_COUNT

# An exact identifier lookup answered by a system-of-record row needs no
# corroboration: the record *is* the fact, not a description of it.  Anything
# below this weight is not an exact, reliable match and gets no exemption.
AUTHORITATIVE_KINDS = frozenset({EvidenceKind.DATABASE, EvidenceKind.APPLICATION_RECORD})
AUTHORITATIVE_WEIGHT = 0.75


def compute(ledger: EvidenceLedger) -> float:
    """Sufficiency of ``ledger`` in [0, 1]."""
    items = ledger.items
    if not items:
        return 0.0
    count_term = min(len(items) / TARGET_EVIDENCE_COUNT, 1.0)
    diversity_term = ledger.diversity()
    top = sorted(items, key=lambda i: i.weight, reverse=True)[:QUALITY_SAMPLE]
    quality_term = sum(i.weight for i in top) / len(top)
    score = (
        SUFFICIENCY_COUNT_WEIGHT * count_term
        + SUFFICIENCY_DIVERSITY_WEIGHT * diversity_term
        + SUFFICIENCY_QUALITY_WEIGHT * quality_term
    )
    return round(min(score, 1.0), 4)


def gaps(ledger: EvidenceLedger) -> list[str]:
    """Plain-language description of what the evidence base still lacks."""
    missing: list[str] = []
    items = ledger.items
    if len(items) < TARGET_EVIDENCE_COUNT:
        missing.append(
            f"only {len(items)} usable item(s) retrieved; {TARGET_EVIDENCE_COUNT} is the corroboration target"
        )
    sources = {i.provenance.source_id for i in items}
    if len(sources) < MIN_INDEPENDENT_SOURCES:
        missing.append(
            f"evidence comes from {len(sources)} source(s); at least {MIN_INDEPENDENT_SOURCES} independent sources are required"
        )
    modalities = {i.modality.value for i in items}
    if len(modalities) < 2:
        missing.append(f"all evidence is {', '.join(sorted(modalities)) or 'absent'}; no cross-modal corroboration")
    if items and max(i.weight for i in items) < 0.5:
        missing.append("no single item is both highly relevant and highly reliable")
    return missing


def names_subject(item: EvidenceItem, focal: Sequence[str]) -> bool:
    """Does this item actually mention what the investigation is about?"""
    if not focal:
        return True
    haystack = f"{item.summary} {item.excerpt} {' '.join(item.entities)}".lower()
    return any(term in haystack for term in focal)


def admit(
    candidates: Iterable[EvidenceItem],
    existing: Sequence[EvidenceItem],
    focal: Sequence[str] = (),
) -> tuple[list[EvidenceItem], dict[str, int]]:
    """Filter candidates into the ledger, recording *why* anything was rejected.

    When the investigation has a focal entity, evidence that never names it is
    rejected as off-subject.  Generic text retrieved from the same document is
    topically similar but decides nothing about *this* entity, and because such
    text is usually plentiful it would otherwise dominate sufficiency and
    diversity.  The gate is skipped entirely when nothing names the subject, so
    a corpus that simply lacks the answer still reaches abstention on the
    evidence rather than on an empty ledger.
    """
    pool = list(candidates)
    grounded = [item for item in pool if names_subject(item, focal)] if focal else pool
    apply_subject_gate = bool(focal) and bool(grounded)

    known = {item.evidence_id for item in existing}
    accepted: list[EvidenceItem] = []
    rejected: dict[str, int] = {}

    def reject(reason: str) -> None:
        rejected[reason] = rejected.get(reason, 0) + 1

    for item in pool:
        if item.evidence_id in known:
            reject("duplicate_of_existing_evidence")
            continue
        if item.relevance < MIN_EVIDENCE_RELEVANCE:
            reject("below_relevance_floor")
            continue
        if apply_subject_gate and not names_subject(item, focal):
            reject("does_not_name_the_subject")
            continue
        known.add(item.evidence_id)
        accepted.append(item)
    return accepted, rejected


def authoritative_item(ledger: EvidenceLedger, intent: QueryIntent | None) -> EvidenceItem | None:
    """The system-of-record row that answers an identifier lookup on its own."""
    if intent is not QueryIntent.LOOKUP_BY_ID:
        return None
    matches = [i for i in ledger.items if i.kind in AUTHORITATIVE_KINDS and i.weight >= AUTHORITATIVE_WEIGHT]
    return max(matches, key=lambda i: i.weight, default=None)
