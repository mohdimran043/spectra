"""Search must be able to say "nothing matched".

Every ranking signal is min-max normalised across the result set, so the best
candidate always scores 1.0 on its strongest signal however bad it is in
absolute terms. Searching for a name absent from the corpus therefore returned
five confident-looking hits - Whisper hallucinations and unrelated screenshots -
because the scorer had no way to express that nothing qualified.

The fix is an admissibility gate on the RAW signals, before normalisation. The
thresholds below come from measurement, not taste:

    query                      lexical    rerank          exact
    'imran' (absent)           0.0000     0.0067-0.2230   no
    'authentication timeout'   1.7-4.9    0.7996-0.9753   no
    'why did the payment fail' 0.9-5.0    0.1527-0.9496   no
    'TX83155'                  1.2-2.6    0.9408-0.9754   yes

Semantic cosine is deliberately not a gate: TX83155, an exact match, scores
0.35-0.47 - overlapping the absent query's 0.30-0.42. It cannot separate them.
"""

from __future__ import annotations

from datetime import datetime, timezone

from spectra_schemas import Chunk, Modality
from spectra_search.candidates import FusedCandidate
from spectra_search.scoring import MIN_RERANK_EVIDENCE, ScoreInput, UnifiedScorer, has_evidence

NOW = datetime(2026, 9, 18, tzinfo=timezone.utc)


def _chunk(chunk_id: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        asset_id="ast_1",
        source_id="src_docs",
        modality=Modality.DOCUMENT,
        text="some indexed text",
        ordinal=0,
    )


def _input(
    chunk_id: str,
    *,
    lexical: float = 0.0,
    semantic: float = 0.0,
    entity: float = 0.0,
    rerank: float | None = None,
    retrievers: tuple[str, ...] = ("dense",),
) -> ScoreInput:
    return ScoreInput(
        fused=FusedCandidate(
            chunk_id=chunk_id,
            rrf_score=0.1,
            retrievers=retrievers,
            ranks={},
            signals={"lexical": lexical, "semantic": semantic, "entity_match": entity},
        ),
        chunk=_chunk(chunk_id),
        source=None,
        rerank=rerank,
    )


class TestHasEvidence:
    def test_lexical_overlap_is_evidence(self):
        assert has_evidence({"lexical": 0.9, "semantic": 0.1, "entity_match": 0.0, "rerank": None}, False)

    def test_an_exact_id_match_is_evidence(self):
        assert has_evidence({"lexical": 0.0, "semantic": 0.1, "entity_match": 0.0, "rerank": None}, True)

    def test_an_entity_match_is_evidence(self):
        assert has_evidence({"lexical": 0.0, "semantic": 0.1, "entity_match": 1.2, "rerank": None}, False)

    def test_a_confident_cross_encoder_is_evidence(self):
        """A true paraphrase shares no words but the reranker recognises it."""
        signals = {"lexical": 0.0, "semantic": 0.6, "entity_match": 0.0, "rerank": 0.85}
        assert has_evidence(signals, False)

    def test_high_cosine_alone_is_not_evidence(self):
        """Cosine cannot separate a match from noise, so it never admits alone."""
        signals = {"lexical": 0.0, "semantic": 0.99, "entity_match": 0.0, "rerank": None}
        assert not has_evidence(signals, False)

    def test_the_absent_query_profile_is_rejected(self):
        """The measured 'imran' profile: no words, no id, weak reranker."""
        signals = {"lexical": 0.0, "semantic": 0.4239, "entity_match": 0.0, "rerank": 0.2230}
        assert not has_evidence(signals, False)

    def test_the_threshold_sits_above_the_measured_noise_ceiling(self):
        assert MIN_RERANK_EVIDENCE > 0.2230


class TestScorerDropsNoise:
    def test_a_query_with_no_evidence_scores_nothing(self):
        # Arrange - the measured 'imran' candidate set
        scorer = UnifiedScorer()
        inputs = [
            _input("c1", semantic=0.3508, rerank=0.2230),
            _input("c2", semantic=0.3092, rerank=0.0236),
            _input("c3", semantic=0.4239, rerank=0.0235),
        ]

        # Act
        scored = scorer.score(inputs, now=NOW)

        # Assert - an empty result set is the honest answer
        assert scored == ()

    def test_genuine_matches_still_score(self):
        # Arrange
        scorer = UnifiedScorer()
        inputs = [
            _input("c1", lexical=4.9367, semantic=0.6599, rerank=0.9753),
            _input("c2", lexical=1.7801, semantic=0.6686, rerank=0.8702),
        ]

        # Act
        scored = scorer.score(inputs, now=NOW)

        # Assert
        assert [row.chunk_id for row in scored] == ["c1", "c2"]

    def test_noise_is_dropped_before_normalisation(self):
        """The surviving hit must not be rescaled against the junk beside it."""
        # Arrange - one real hit among the 'imran' noise
        scorer = UnifiedScorer()
        inputs = [
            _input("real", lexical=4.9367, semantic=0.6599, rerank=0.9753),
            _input("noise1", semantic=0.4239, rerank=0.0235),
            _input("noise2", semantic=0.3092, rerank=0.0236),
        ]

        # Act
        scored = scorer.score(inputs, now=NOW)

        # Assert
        assert [row.chunk_id for row in scored] == ["real"]

    def test_an_exact_id_survives_a_weak_reranker(self):
        # Arrange - TX83155's measured profile: low cosine, but exact
        scorer = UnifiedScorer()
        inputs = [_input("c1", lexical=1.18, semantic=0.3762, entity=1.18, retrievers=("exact_id",))]

        # Act
        scored = scorer.score(inputs, now=NOW)

        # Assert
        assert len(scored) == 1
        assert scored[0].is_exact
