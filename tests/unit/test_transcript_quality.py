"""Speech recognition invents text, and an index is forever.

Whisper decodes silence and music into confident-sounding filler. Six of the
122 chunks indexed from the demo corpus were exactly this: "Thank you for
watching!", "Oh", "© transcript Emily Beynon". Once indexed they are searchable
content, and they surfaced for any query with nothing better to match - which is
how a search for a name absent from the corpus returned five results.

The strings below are the real ones found in the index, not invented examples.
The filter runs at ingestion, where the cost is paid once.

The hard part is not catching them; it is not catching real speech. A meeting
transcript that opens "Thank you, Marcus, for the update" must survive, so
matching is on the whole de-duplicated utterance, never a substring.
"""

from __future__ import annotations

from spectra_ingestion.chunking import (
    MIN_TRANSCRIPT_CHARS,
    TranscriptWindow,
    drop_hallucinated,
    is_hallucinated_transcript,
)

#: Verbatim from the index before the purge.
FOUND_IN_INDEX = (
    "Thank you. Thank you.",
    "© transcript Emily Beynon © transcript Emily Beynon",
    "Thank you for watching. Thank you for watching.",
    "Thank you for watching!",
    "Oh",
)

REAL_SPEECH = (
    "The payment failed at 02:03 with an upstream auth timeout.",
    "Marcus said the connection pool was exhausted.",
    "Thank you, Marcus, for the update on the incident.",
    "Thanks for watching the dashboard while I was out, it helped.",
    "No fraud rule fired and the balance was sufficient.",
)


def _window(ordinal: int, text: str) -> TranscriptWindow:
    return TranscriptWindow(
        ordinal=ordinal,
        text=text,
        start_seconds=float(ordinal),
        end_seconds=float(ordinal) + 1.0,
        segment_count=1,
    )


class TestIsHallucinatedTranscript:
    def test_every_utterance_found_in_the_index_is_caught(self):
        for text in FOUND_IN_INDEX:
            assert is_hallucinated_transcript(text) is True, text

    def test_real_speech_survives(self):
        for text in REAL_SPEECH:
            assert is_hallucinated_transcript(text) is False, text

    def test_a_thank_you_inside_a_real_sentence_is_not_a_match(self):
        """Matching on substrings would delete genuine speech."""
        assert is_hallucinated_transcript("Thank you, Marcus, for the update.") is False

    def test_repetition_is_collapsed_before_matching(self):
        """Looping on one phrase is the signature of decoding silence."""
        assert is_hallucinated_transcript("bye bye bye bye bye bye") is True

    def test_repeated_real_speech_is_kept(self):
        repeated = "The pool was exhausted. The pool was exhausted."
        assert is_hallucinated_transcript(repeated) is False

    def test_empty_and_punctuation_only_text_is_noise(self):
        assert is_hallucinated_transcript("") is True
        assert is_hallucinated_transcript("   ") is True
        assert is_hallucinated_transcript("... !!! ???") is True

    def test_credit_lines_are_noise(self):
        assert is_hallucinated_transcript("Subtitles by the Amara.org community") is True
        assert is_hallucinated_transcript("Transcription by ESO") is True

    def test_anything_shorter_than_the_floor_is_noise(self):
        assert is_hallucinated_transcript("a b") is True
        assert MIN_TRANSCRIPT_CHARS >= 8


class TestDropHallucinated:
    def test_only_the_noise_is_removed(self):
        # Arrange
        windows = [
            _window(0, "The payment failed at 02:03 with an upstream auth timeout."),
            _window(1, "Thank you for watching!"),
            _window(2, "Marcus said the connection pool was exhausted."),
            _window(3, "Oh"),
        ]

        # Act
        kept = drop_hallucinated(windows)

        # Assert
        assert [w.ordinal for w in kept] == [0, 2]

    def test_an_all_noise_transcript_yields_nothing(self):
        windows = [_window(index, text) for index, text in enumerate(FOUND_IN_INDEX)]
        assert drop_hallucinated(windows) == []

    def test_a_clean_transcript_is_unchanged(self):
        windows = [_window(index, text) for index, text in enumerate(REAL_SPEECH)]
        assert drop_hallucinated(windows) == windows
