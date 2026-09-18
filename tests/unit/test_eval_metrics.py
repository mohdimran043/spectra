"""Metric correctness, asserted against hand-computed values."""

from __future__ import annotations

import math

import pytest
from spectra_eval.datasets.benchmark import parse_target
from spectra_eval.metrics import (
    abstention_outcome,
    claim_support,
    entity_resolution_prf,
    evidence_completeness,
    investigation_success,
    mrr,
    ndcg_at_k,
    percentiles,
    precision_at_k,
    recall_at_k,
    term_overlap,
)

T = parse_target


class TestRetrievalMetrics:
    def test_recall_counts_distinct_expectations(self):
        produced = [T("document:A"), T("document:B"), T("document:C")]
        expected = [T("document:A"), T("document:C"), T("document:Z")]
        assert recall_at_k(produced, expected, k=3) == pytest.approx(2 / 3)

    def test_recall_respects_the_cutoff(self):
        produced = [T("document:X"), T("document:Y"), T("document:A")]
        assert recall_at_k(produced, [T("document:A")], k=2) == 0.0
        assert recall_at_k(produced, [T("document:A")], k=3) == 1.0

    def test_precision_is_relevant_over_returned(self):
        produced = [T("document:A"), T("document:X"), T("document:B"), T("document:Y")]
        expected = [T("document:A"), T("document:B")]
        assert precision_at_k(produced, expected, k=4) == pytest.approx(0.5)

    def test_mrr_is_the_reciprocal_of_the_first_hit(self):
        produced = [T("document:X"), T("document:Y"), T("document:A")]
        assert mrr(produced, [T("document:A")]) == pytest.approx(1 / 3)

    def test_mrr_is_zero_when_nothing_matches(self):
        assert mrr([T("document:X")], [T("document:A")]) == 0.0

    def test_ndcg_is_one_for_a_perfect_ranking(self):
        expected = [T("document:A"), T("document:B")]
        assert ndcg_at_k(expected, expected, k=2) == pytest.approx(1.0)

    def test_ndcg_penalises_a_late_hit_by_the_known_factor(self):
        """One relevant item at rank 2: DCG = 1/log2(3), IDCG = 1/log2(2) = 1."""
        produced = [T("document:X"), T("document:A")]
        assert ndcg_at_k(produced, [T("document:A")], k=2) == pytest.approx(1 / math.log2(3), abs=1e-6)

    def test_page_qualifier_must_match_when_stated(self):
        produced = [T("document:DOC7033#page=2")]
        assert recall_at_k(produced, [T("document:DOC7033#page=14")], k=5) == 0.0
        assert recall_at_k(produced, [T("document:DOC7033")], k=5) == 1.0

    def test_video_timestamp_tolerance(self):
        produced = [T("video:VID003#t=2550-2580")]
        assert recall_at_k(produced, [T("video:VID003#t=2537-2581")], k=5) == 1.0
        far = [T("video:VID003#t=10-20")]
        assert recall_at_k(far, [T("video:VID003#t=2537-2581")], k=5) == 0.0

    def test_empty_expectation_is_vacuously_satisfied(self):
        assert recall_at_k([], [], k=5) == 1.0


class TestEntityResolution:
    def test_perfect_resolution(self):
        result = entity_resolution_prf(["TX82931", "C82731"], ["TX82931", "C82731"])
        assert (result.precision, result.recall, result.f1) == (1.0, 1.0, 1.0)

    def test_surface_variants_normalise_to_the_same_key(self):
        assert entity_resolution_prf(["tx-82931"], ["TX82931"]).f1 == 1.0

    def test_partial_resolution_scores_correctly(self):
        result = entity_resolution_prf(["TX82931", "WRONG"], ["TX82931", "C82731"])
        assert result.precision == pytest.approx(0.5)
        assert result.recall == pytest.approx(0.5)


class TestEvidenceAndClaims:
    def test_completeness_is_the_fraction_of_expectations_cited(self):
        produced = [T("document:A#page=14")]
        expected = [T("document:A#page=14"), T("video:V#t=100-120")]
        assert evidence_completeness(produced, expected) == pytest.approx(0.5)

    def test_claim_support_requires_citations_that_exist(self):
        answer = "The service timed out [E1]. The pool was exhausted [E2]."
        assert claim_support(answer, ["E1", "E2"]) == pytest.approx(1.0)

    def test_a_citation_to_a_nonexistent_item_is_not_support(self):
        assert claim_support("The service timed out [E9].", ["E1"]) == 0.0

    def test_an_uncited_assertion_counts_against_support(self):
        answer = "The service timed out [E1]. Fraud was definitely involved."
        assert claim_support(answer, ["E1"]) == pytest.approx(0.5)

    def test_headings_are_not_treated_as_assertions(self):
        assert claim_support("Summary. The service timed out [E1].", ["E1"]) == pytest.approx(1.0)


class TestReasoningAndCalibration:
    def test_status_mismatch_fails_outright(self):
        assert investigation_success("supported", "insufficient_evidence", "x", "y") == 0.0

    def test_matching_status_with_the_right_terms_scores_high(self):
        score = investigation_success(
            "supported", "supported",
            "The authentication service timed out and the connection pool was exhausted.",
            "authentication timed out connection pool exhausted",
        )
        assert score == pytest.approx(1.0)

    def test_matching_status_with_wrong_content_scores_the_floor(self):
        assert investigation_success("supported", "supported", "Unrelated text.",
                                     "authentication pool exhausted") == pytest.approx(0.5)

    def test_term_overlap_ignores_stopwords(self):
        assert term_overlap("the authentication service", "authentication service") == 1.0

    @pytest.mark.parametrize(
        "produced,expected,outcome",
        [
            ("insufficient_evidence", "insufficient_evidence", "correctly_abstained"),
            ("supported", "insufficient_evidence", "wrongly_answered"),
            ("insufficient_evidence", "supported", "wrongly_abstained"),
            ("supported", "supported", "correctly_answered"),
        ],
    )
    def test_abstention_classification(self, produced, expected, outcome):
        assert abstention_outcome(produced, expected) == outcome

    def test_percentiles_on_a_known_series(self):
        result = percentiles([10.0, 20.0, 30.0, 40.0, 50.0])
        assert result["p50"] == 30.0
        assert result["max"] == 50.0
        assert result["mean"] == 30.0

    def test_percentiles_of_nothing_are_zero(self):
        assert percentiles([])["p50"] == 0.0
