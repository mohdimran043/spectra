"""A cited answer must survive its own citation check.

The grounding law drops any sentence that asserts something without a valid
citation.  Models do not reliably put the citation inside every sentence: they
write the prose and then group `[E1][E2][E5]` into a trailing block.  Splitting
naively made that block a "sentence" of its own - the only one carrying a
citation - so every prose sentence was dropped as unsupported and the published
answer was a row of citation markers with nothing asserted.

These tests pin both halves of the fix: a bare run of citations is never a
sentence, and an answer that loses all of its prose is not published at all.
"""

from __future__ import annotations

from spectra_agent.grounding import labels_for, split_sentences, unsupported_sentences
from spectra_agent.synthesis import carries_prose

LABELS = labels_for([f"evd_{index}" for index in range(1, 9)])

ROOT_CAUSE = "TX83155 failed because the authorisation call timed out."
SECOND = "The fraud rule did not fire."


def _kept(text: str) -> str:
    unsupported = set(unsupported_sentences(text, LABELS))
    return " ".join(s for s in split_sentences(text) if s not in unsupported)


class TestTrailingCitationBlocks:
    def test_a_bare_citation_run_is_not_its_own_sentence(self):
        # Arrange
        text = f"{ROOT_CAUSE} {SECOND} [E1][E2][E5]"

        # Act
        sentences = split_sentences(text)

        # Assert
        assert sentences == [ROOT_CAUSE, f"{SECOND} [E1][E2][E5]"]

    def test_a_citation_block_on_its_own_line_attaches_to_the_prose_above(self):
        # Arrange
        text = f"{ROOT_CAUSE}\n\n[E1][E2]"

        # Act / Assert
        assert split_sentences(text) == [f"{ROOT_CAUSE} [E1][E2]"]

    def test_the_cited_sentence_survives_the_grounding_check(self):
        # Arrange
        text = f"{ROOT_CAUSE} {SECOND} [E1][E2][E5]"

        # Act
        kept = _kept(text)

        # Assert - the assertion it carries is published, not just its markers
        assert SECOND in kept
        assert kept != "[E1][E2][E5]"

    def test_an_uncited_leading_sentence_is_still_dropped(self):
        """The fix normalises formatting; it does not relax the grounding law."""
        # Arrange
        text = f"{ROOT_CAUSE} {SECOND} [E1]"

        # Act
        kept = _kept(text)

        # Assert
        assert ROOT_CAUSE not in kept

    def test_inline_citations_are_unaffected(self):
        # Arrange
        text = "The authorisation call timed out [E1][E2]. No fraud rule fired [E5]."

        # Act / Assert
        assert split_sentences(text) == [
            "The authorisation call timed out [E1][E2].",
            "No fraud rule fired [E5].",
        ]
        assert _kept(text) == text

    def test_a_citation_only_answer_has_no_sentence_to_attach_to(self):
        # Arrange / Act / Assert - nothing precedes it, so nothing is invented
        assert split_sentences("[E1][E2]") == ["[E1][E2]"]


class TestCarriesProse:
    def test_citation_markers_alone_are_not_prose(self):
        assert carries_prose("[E1][E2][E5][E7][E8]") is False

    def test_an_empty_answer_is_not_prose(self):
        assert carries_prose("   ") is False

    def test_punctuation_around_the_markers_is_still_not_prose(self):
        assert carries_prose("[E1], [E2].") is False

    def test_an_asserted_sentence_is_prose(self):
        assert carries_prose(f"{ROOT_CAUSE} [E1]") is True
