"""Deterministic contradiction detection used when the evidence service is absent.

Two kinds are detected, both grounded in the evidence text itself:

* **outcome conflicts** - one item says an outcome happened, another says its
  opposite happened, about the same entity;
* **value conflicts** - two items state different values for the same labelled
  field of the same entity.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from itertools import combinations

from spectra_schemas import Contradiction, EvidenceItem

from ...causal_lexicon import NEGATION_MAP

_FIELD_VALUE = re.compile(r"\b([a-z][a-z_ ]{2,24}?)\s*[:=]\s*([A-Za-z0-9.,%-]+)")
# Conflicts between unrelated items are noise, so a shared entity (or a shared
# salient identifier) is required before a pair is even compared.
MIN_SHARED_ENTITIES = 1
# Outcome conflicts are the severe kind: they change the answer.
OUTCOME_SEVERITY = 0.8
VALUE_SEVERITY = 0.5


def detect(
    items: Sequence[EvidenceItem],
    limit: int = 20,
    focal: Sequence[str] = (),
) -> list[Contradiction]:
    """Contradictions between evidence items, strongest first, one per conflict.

    Two rules keep this honest and keep the count meaningful:

    * **One conflict is reported once.** The same disagreement - "approved"
      against "rejected" - normally appears across many document pairs. Listing
      each pair turned a single disagreement into eighteen, which reads as a
      corpus in chaos rather than one thing to resolve. Pairs are collapsed by
      (subject, disagreement) and the strongest is kept.
    * **A conflict must bear on the question.** When the investigation has focal
      entities, unrelated disagreements elsewhere in the corpus are not this
      investigation's business, and surfacing them on a question they have
      nothing to do with is noise.
    """
    wanted = {entity for entity in focal if entity}
    strongest: dict[str, Contradiction] = {}

    for left, right in combinations(list(items), 2):
        shared = _shared_subject(left, right)
        if not shared:
            continue
        if wanted and not (set(shared) & wanted):
            continue
        conflict = _outcome_conflict(left, right) or _value_conflict(left, right)
        if conflict is None:
            continue
        statement, detail, kind, severity = conflict

        # Key on the disagreement itself. Keying on the entity too let the same
        # conflict through repeatedly, because `shared[0]` varies with whichever
        # entity two particular documents happen to share first.
        key = statement.strip().lower()
        candidate = Contradiction(
            contradiction_id=f"con_{left.evidence_id[-6:]}_{right.evidence_id[-6:]}",
            statement=statement,
            evidence_a=left.evidence_id,
            evidence_b=right.evidence_id,
            kind=kind,
            detail=detail,
            severity=severity,
            entity_id=shared[0],
        )
        previous = strongest.get(key)
        if previous is None or candidate.severity > previous.severity:
            strongest[key] = candidate

    found = sorted(strongest.values(), key=lambda c: c.severity, reverse=True)
    return found[:limit]


def _text(item: EvidenceItem) -> str:
    return f"{item.summary} {item.excerpt}".lower()


def _shared_subject(left: EvidenceItem, right: EvidenceItem) -> list[str]:
    shared = [entity for entity in left.entities if entity in right.entities]
    if len(shared) >= MIN_SHARED_ENTITIES:
        return shared
    left_ids = set(re.findall(r"\b[A-Z]{2,6}[-_]?\d{3,}\b", left.summary + left.excerpt))
    right_ids = set(re.findall(r"\b[A-Z]{2,6}[-_]?\d{3,}\b", right.summary + right.excerpt))
    return sorted(left_ids & right_ids)


def _outcome_conflict(left: EvidenceItem, right: EvidenceItem) -> tuple[str, str, str, float] | None:
    left_text, right_text = _text(left), _text(right)
    for term, antonyms in NEGATION_MAP.items():
        for antonym in antonyms:
            if term in left_text and antonym in right_text:
                return (
                    f"One source reports '{term}' while another reports '{antonym}'",
                    f"{left.citation()} says '{term}'; {right.citation()} says '{antonym}'",
                    "outcome_conflict",
                    OUTCOME_SEVERITY,
                )
            if term in right_text and antonym in left_text:
                return (
                    f"One source reports '{antonym}' while another reports '{term}'",
                    f"{left.citation()} says '{antonym}'; {right.citation()} says '{term}'",
                    "outcome_conflict",
                    OUTCOME_SEVERITY,
                )
    return None


def _value_conflict(left: EvidenceItem, right: EvidenceItem) -> tuple[str, str, str, float] | None:
    left_fields = dict(_FIELD_VALUE.findall(_text(left)))
    right_fields = dict(_FIELD_VALUE.findall(_text(right)))
    for field, left_value in left_fields.items():
        right_value = right_fields.get(field)
        if right_value is None or right_value == left_value:
            continue
        return (
            f"'{field.strip()}' is reported as {left_value} and as {right_value}",
            f"{left.citation()} -> {left_value}; {right.citation()} -> {right_value}",
            "value_conflict",
            VALUE_SEVERITY,
        )
    return None
