"""One disagreement is reported once, and only when it concerns the question.

Reporting every document pair that exhibits the same conflict turned a single
disagreement into eighteen, which reads as a corpus in chaos rather than one
thing to resolve - and surfaced conflicts on questions they had nothing to do
with.
"""

from __future__ import annotations

from spectra_agent.agents.contradiction.contradictions import detect
from spectra_schemas import (
    DocumentLocator,
    EvidenceItem,
    EvidenceKind,
    Modality,
    Provenance,
)

URI = "spectra://objects/ab/" + "c" * 64
INCIDENT = "ent_incident_1"
OTHER = "ent_incident_2"


def _item(evidence_id: str, summary: str, entity: str) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        kind=EvidenceKind.DOCUMENT,
        modality=Modality.DOCUMENT,
        summary=summary,
        provenance=Provenance(
            source_id=f"src_{evidence_id}",
            modality=Modality.DOCUMENT,
            object_uri=URI,
            locator=DocumentLocator(document_id=f"DOC{evidence_id}", page=1),
        ),
        relevance=0.9,
        reliability=0.9,
        entities=[entity],
    )


APPROVED = "The incident was approved by the risk board."
REJECTED = "The incident was rejected pending more data."


class TestDeduplication:
    def test_the_same_disagreement_is_reported_once(self):
        # Four documents, two saying approved and two saying rejected: one
        # disagreement, not the four pairings of it.
        items = [
            _item("a1", APPROVED, INCIDENT),
            _item("a2", APPROVED, INCIDENT),
            _item("r1", REJECTED, INCIDENT),
            _item("r2", REJECTED, INCIDENT),
        ]
        found = detect(items)
        assert len(found) == 1, [c.statement for c in found]

    def test_distinct_disagreements_are_still_separate(self):
        items = [
            _item("a1", APPROVED, INCIDENT),
            _item("r1", REJECTED, INCIDENT),
            _item("u1", "The service was reported up.", INCIDENT),
            _item("d1", "The service was reported down.", INCIDENT),
        ]
        assert len(detect(items)) >= 2


class TestScoping:
    def test_a_conflict_about_another_subject_is_ignored(self):
        items = [_item("a1", APPROVED, OTHER), _item("r1", REJECTED, OTHER)]
        assert detect(items, focal=[INCIDENT]) == []

    def test_a_conflict_about_the_focal_subject_is_reported(self):
        items = [_item("a1", APPROVED, INCIDENT), _item("r1", REJECTED, INCIDENT)]
        found = detect(items, focal=[INCIDENT])
        assert len(found) == 1
        assert found[0].entity_id == INCIDENT

    def test_no_focal_entities_means_no_scoping(self):
        items = [_item("a1", APPROVED, OTHER), _item("r1", REJECTED, OTHER)]
        assert len(detect(items, focal=[])) == 1

    def test_evidence_about_different_subjects_never_conflicts(self):
        items = [_item("a1", APPROVED, INCIDENT), _item("r1", REJECTED, OTHER)]
        assert detect(items) == []


class TestLimit:
    def test_the_limit_is_respected(self):
        items = [
            _item(f"a{i}", f"Item {i} was approved on line {i}.", INCIDENT) for i in range(6)
        ] + [_item(f"r{i}", f"Item {i} was rejected on line {i}.", INCIDENT) for i in range(6)]
        assert len(detect(items, limit=2)) <= 2
