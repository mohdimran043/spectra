"""Entity grounding: evidence and hypotheses must be about the investigated subject.

Without these gates, generic text retrieved from the same document seeds
plausible-but-unfounded explanations and, being plentiful, outweighs the one
passage that actually names the entity.
"""

from __future__ import annotations

from spectra_agent.sufficiency import admit, names_subject
from spectra_schemas import (
    DocumentLocator,
    EvidenceItem,
    EvidenceKind,
    Modality,
    Provenance,
)

URI = "spectra://objects/ab/" + "c" * 64


def _item(evidence_id: str, summary: str, relevance: float = 0.8, entities: list[str] | None = None):
    return EvidenceItem(
        evidence_id=evidence_id,
        kind=EvidenceKind.DOCUMENT,
        modality=Modality.DOCUMENT,
        summary=summary,
        provenance=Provenance(
            source_id="src_docs",
            modality=Modality.DOCUMENT,
            object_uri=URI,
            locator=DocumentLocator(document_id="DOC1", page=1),
        ),
        relevance=relevance,
        reliability=0.7,
        entities=entities or [],
    )


SIGNAL = "Transaction TX82931 failed with an authentication timeout."
FILLER = "Routine capacity notes. No incidents were recorded this week."


class TestNamesSubject:
    def test_matches_on_the_summary(self):
        assert names_subject(_item("a", SIGNAL), ["tx82931"])

    def test_matches_on_a_linked_entity(self):
        assert names_subject(_item("a", "The charge failed.", entities=["TX82931"]), ["tx82931"])

    def test_rejects_text_that_never_names_the_subject(self):
        assert not names_subject(_item("b", FILLER), ["tx82931"])

    def test_no_focal_terms_means_everything_qualifies(self):
        assert names_subject(_item("b", FILLER), [])


class TestAdmit:
    def test_off_subject_evidence_is_rejected_with_a_reason(self):
        candidates = [_item("signal", SIGNAL), *[_item(f"filler{i}", FILLER) for i in range(5)]]
        accepted, rejected = admit(candidates, [], ["tx82931"])

        assert [item.evidence_id for item in accepted] == ["signal"]
        assert rejected["does_not_name_the_subject"] == 5

    def test_the_gate_is_skipped_when_nothing_names_the_subject(self):
        """Otherwise an absent answer would produce an empty ledger rather than
        an honest 'the evidence does not support this' outcome."""
        candidates = [_item(f"filler{i}", FILLER) for i in range(3)]
        accepted, rejected = admit(candidates, [], ["tx99999"])

        assert len(accepted) == 3
        assert "does_not_name_the_subject" not in rejected

    def test_the_relevance_floor_still_applies(self):
        accepted, rejected = admit([_item("weak", SIGNAL, relevance=0.01)], [], ["tx82931"])
        assert accepted == []
        assert rejected["below_relevance_floor"] == 1

    def test_duplicates_are_rejected_against_the_existing_ledger(self):
        existing = [_item("signal", SIGNAL)]
        accepted, rejected = admit([_item("signal", SIGNAL)], existing, ["tx82931"])
        assert accepted == []
        assert rejected["duplicate_of_existing_evidence"] == 1

    def test_without_focal_terms_everything_relevant_is_admitted(self):
        candidates = [_item("signal", SIGNAL), _item("filler", FILLER)]
        accepted, _ = admit(candidates, [], [])
        assert len(accepted) == 2
