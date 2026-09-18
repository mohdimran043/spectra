"""A negated outcome is not the outcome.

Stance is decided by looking for a claim's *competing* outcomes in the evidence
text. Matching them as bare substrings read agreement as conflict: a screenshot
saying "the payment could **not** be authorised because the authentication
service did not respond in time" was filed as contradicting the claim that the
transaction failed on an authorisation timeout - because the word "authorised"
appears in it. The claim it actually corroborated was penalised for it and lost
the lead to a weaker one.

Two rules are pinned here: a competing outcome only counts when it is asserted
(not sitting behind a negation), and only when it matches whole words - so
"authorised" inside "unauthorised" is a miss, not a hit.
"""

from __future__ import annotations

from spectra_agent.causal_lexicon import asserted
from spectra_agent.stance import classify
from spectra_schemas import (
    DocumentLocator,
    EvidenceItem,
    EvidenceKind,
    EvidenceStance,
    Modality,
    Provenance,
)

URI = "spectra://objects/ab/" + "c" * 64

CLAIM = (
    "TX83155 was declined with upstream_auth_timeout because the authorisation "
    "call never returned, not because of fraud scoring."
)


def _item(summary: str, excerpt: str = "") -> EvidenceItem:
    return EvidenceItem(
        evidence_id="evd_1",
        kind=EvidenceKind.DOCUMENT,
        modality=Modality.DOCUMENT,
        summary=summary,
        excerpt=excerpt,
        provenance=Provenance(
            source_id="src_docs",
            modality=Modality.DOCUMENT,
            object_uri=URI,
            locator=DocumentLocator(kind="document", document_id="DOC1", page=1),
        ),
    )


class TestAsserted:
    def test_a_plain_statement_asserts_the_phrase(self):
        assert asserted("authorised", "the payment was authorised at 02:03") is True

    def test_a_negated_statement_does_not(self):
        assert asserted("authorised", "the payment could not be authorised") is False

    def test_never_negates(self):
        assert asserted("approved", "the change was never approved by the board") is False

    def test_failed_to_negates(self):
        assert asserted("authorise", "the gateway failed to authorise tx83155") is False

    def test_a_prefix_is_not_a_match(self):
        """'authorised' inside 'unauthorised' means the opposite."""
        assert asserted("authorised", "an unauthorised request was logged") is False

    def test_a_suffix_is_not_a_match(self):
        assert asserted("cleared", "the backlog was uncleared overnight") is False

    def test_a_distant_negation_does_not_reach(self):
        text = "the call did not complete. much later the payment was authorised"
        assert asserted("authorised", text) is True

    def test_a_multi_word_phrase_is_matched_whole(self):
        assert asserted("insufficient funds", "declined for insufficient funds") is True
        assert asserted("insufficient funds", "not declined for insufficient funds") is False


class TestClassify:
    def test_corroborating_evidence_is_not_read_as_conflict(self):
        """The regression: this exhibit agrees with the claim."""
        # Arrange
        item = _item(
            "The payment could not be authorised because the authentication "
            "service did not respond in time.",
            excerpt="Checkout Merchant portal Authorisation failed. Reference: TX83155.",
        )

        # Act
        stance = classify(CLAIM, item)

        # Assert
        assert stance is not EvidenceStance.CONTRADICTING

    def test_a_genuinely_competing_outcome_still_conflicts(self):
        # Arrange - this one really does say the opposite
        item = _item(
            "TX83155 was authorised at 02:03 by the authorisation service and the "
            "call returned cleanly."
        )

        # Act / Assert
        assert classify(CLAIM, item) is EvidenceStance.CONTRADICTING

    def test_unrelated_text_stays_neutral(self):
        item = _item("The cafeteria menu for Thursday was updated.")
        assert classify(CLAIM, item) is EvidenceStance.NEUTRAL
