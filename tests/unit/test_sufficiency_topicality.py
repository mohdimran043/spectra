"""Evidence that is not about the question cannot make an answer sufficient.

Retrieval always returns its best matches, so a question the corpus cannot
answer still yields well-scored, diverse evidence about something else. Without
this signal the system confidently answers a question it has no evidence for.
"""

from __future__ import annotations

from spectra_agent.sufficiency import compute, topicality
from spectra_schemas import (
    DocumentLocator,
    EvidenceItem,
    EvidenceKind,
    EvidenceLedger,
    Modality,
    Provenance,
)

URI = "spectra://objects/ab/" + "c" * 64
ON_TOPIC = "Transaction TX83155 failed with an upstream authorisation timeout."
OFF_TOPIC = "Quarterly capacity planning notes for the reporting cluster."


def _item(evidence_id: str, summary: str, source: str = "src_docs") -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        kind=EvidenceKind.DOCUMENT,
        modality=Modality.DOCUMENT,
        summary=summary,
        provenance=Provenance(
            source_id=source,
            modality=Modality.DOCUMENT,
            object_uri=URI,
            locator=DocumentLocator(document_id=f"DOC{evidence_id}", page=1),
        ),
        relevance=0.9,
        reliability=0.9,
    )


def _ledger(*summaries: str) -> EvidenceLedger:
    return EvidenceLedger().with_items(
        [_item(str(i), text, source=f"src_{i}") for i, text in enumerate(summaries)]
    )


class TestTopicality:
    def test_all_on_topic_scores_one(self):
        ledger = _ledger(ON_TOPIC, ON_TOPIC)
        assert topicality(ledger, "why did transaction TX83155 fail") == 1.0

    def test_none_on_topic_scores_zero(self):
        ledger = _ledger(OFF_TOPIC, OFF_TOPIC, OFF_TOPIC)
        assert topicality(ledger, "the Antarctic division 2041 budget decision") == 0.0

    def test_one_on_topic_item_is_only_half_a_gate(self):
        ledger = _ledger(ON_TOPIC, OFF_TOPIC)
        assert topicality(ledger, "transaction TX83155 authorisation") == 0.5

    def test_two_on_topic_items_open_the_gate_fully(self):
        """Supporting context around real matches is not noise."""
        ledger = _ledger(ON_TOPIC, ON_TOPIC, OFF_TOPIC, OFF_TOPIC, OFF_TOPIC)
        assert topicality(ledger, "transaction TX83155 authorisation") == 1.0

    def test_a_question_with_no_distinctive_terms_does_not_veto(self):
        """With nothing to match on this signal must stay silent, not block."""
        ledger = _ledger(OFF_TOPIC)
        assert topicality(ledger, "what happened") == 1.0

    def test_empty_ledger_is_not_penalised_here(self):
        assert topicality(EvidenceLedger(), "anything") == 1.0


class TestCompute:
    def test_off_topic_evidence_is_never_sufficient(self):
        """The calibration failure this exists to prevent."""
        ledger = _ledger(OFF_TOPIC, OFF_TOPIC, OFF_TOPIC, OFF_TOPIC)
        without_question = compute(ledger)
        with_question = compute(ledger, "the Antarctic division 2041 budget decision")

        assert without_question > 0.0, "diverse, well-scored evidence scores well on its own"
        assert with_question == 0.0, "but it is worthless for a question it does not address"

    def test_on_topic_evidence_keeps_its_score(self):
        ledger = _ledger(ON_TOPIC, ON_TOPIC, ON_TOPIC, ON_TOPIC)
        question = "why did transaction TX83155 fail"
        assert compute(ledger, question) == compute(ledger)

    def test_an_empty_ledger_is_zero(self):
        assert compute(EvidenceLedger(), "anything") == 0.0

    def test_a_single_on_topic_item_is_damped_not_zeroed(self):
        ledger = _ledger(ON_TOPIC, OFF_TOPIC)
        question = "transaction TX83155 authorisation"
        damped = compute(ledger, question)
        assert 0.0 < damped < compute(ledger)

    def test_an_answerable_question_is_not_penalised_for_context(self):
        """The failure this gate replaced: abstaining on an answerable question."""
        ledger = _ledger(ON_TOPIC, ON_TOPIC, OFF_TOPIC, OFF_TOPIC)
        question = "why did transaction TX83155 fail"
        assert compute(ledger, question) == compute(ledger)
