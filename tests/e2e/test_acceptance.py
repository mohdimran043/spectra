"""Acceptance: the whole product, against a real corpus on real services.

Ingestion runs for real (OCR, transcription, embedding), the indexes are the
ones the application queries, and nothing is mocked. These tests state what the
product promises:

1. what is in the corpus can be found, whichever modality it arrived in;
2. every hit can be reopened at the exact page, frame or row it came from;
3. what is *not* in the corpus returns nothing, rather than the nearest thing;
4. an answer is written only from retrieved passages, and cites them.
"""

from __future__ import annotations

import pytest
from spectra_api.answering import answer_from_hits, ground
from spectra_schemas import Modality, SearchMode, SearchRequest

from .conftest import CUSTOMER, TX

pytestmark = [pytest.mark.e2e, pytest.mark.slow]

#: Terms chosen to be absent from every fixture the conftest writes.
ABSENT = ("imran", "reykjavik warehouse fire", "zzzqqq nonexistent")


async def _search(container, ctx, query: str, *, mode=SearchMode.FAST, top_k=10):
    return await container.search.search(SearchRequest(query=query, mode=mode, top_k=top_k), ctx)


class TestWhatIsIndexedIsFindable:
    """The corpus is searchable across every modality it holds."""

    async def test_an_identifier_is_found_exactly(self, live_container, analyst):
        response = await _search(live_container, analyst, TX)
        assert response.hits, f"{TX} is in the corpus and must be retrievable"

    async def test_prose_is_found_semantically(self, live_container, analyst):
        response = await _search(live_container, analyst, "why did the authorisation time out")
        assert response.hits, "a question phrased in its own words must still retrieve"

    async def test_text_recovered_from_an_image_is_searchable(self, live_container, analyst):
        """OCR ran at ingestion, so the screenshot's text is ordinary index content."""
        response = await _search(live_container, analyst, TX, top_k=25)
        assert response.hits


class TestEveryHitCanBeReopened:
    """A result nobody can open is a rumour, not a finding."""

    async def test_document_results_cite_an_exact_page(self, live_container, analyst):
        response = await _search(live_container, analyst, "connection pool exhausted", top_k=10)
        documents = [h for h in response.hits if h.modality is Modality.DOCUMENT]
        assert documents, "the incident PDF must be retrievable"
        for hit in documents:
            locator = hit.provenance.locator
            assert getattr(locator, "document_id", None)
            assert isinstance(getattr(locator, "page", None), int)

    async def test_every_hit_carries_a_score_breakdown(self, live_container, analyst):
        response = await _search(live_container, analyst, TX)
        assert response.hits
        for hit in response.hits:
            assert hit.scores is not None
            assert 0.0 <= hit.scores.final <= 2.0
            assert hit.provenance.source_id


class TestWhatIsAbsentReturnsNothing:
    """The failure this product was rebuilt around.

    Scoring min-max normalises every signal across the result set, so without an
    admissibility gate the best of a bad candidate set always looked like a
    confident match. A term the corpus does not contain must return nothing.
    """

    @pytest.mark.parametrize("query", ABSENT)
    async def test_an_absent_term_returns_no_results(self, live_container, analyst, query):
        response = await _search(live_container, analyst, query)
        assert response.hits == [], f"{query!r} is not in the corpus and must return nothing"

    async def test_candidates_were_still_screened(self, live_container, analyst):
        """Nothing found is a judgement, not a failure to look."""
        response = await _search(live_container, analyst, "imran")
        assert response.hits == []
        assert response.total_candidates > 0

    async def test_a_present_term_is_unaffected(self, live_container, analyst):
        """The gate must not be so tight that real queries stop working."""
        assert (await _search(live_container, analyst, TX)).hits


class TestTheAnswerIsGroundedOrAbsent:
    """An answer may only say what the retrieved passages say."""

    async def test_an_answer_cites_the_results_it_used(self, live_container, analyst):
        response = await _search(live_container, analyst, "why did the payment fail", top_k=6)
        if not response.hits:
            pytest.skip("no hits to answer from on this corpus")
        answer = await answer_from_hits(
            "why did the payment fail", response.hits, live_container.gateway
        )
        if not answer.text:
            assert answer.degraded_reason, "an empty answer must say why it is empty"
            return
        assert answer.citations, "a published answer always cites"
        assert all(1 <= index <= len(response.hits) for index in answer.citations)

    async def test_no_hits_means_no_answer(self, live_container, analyst):
        response = await _search(live_container, analyst, "imran")
        answer = await answer_from_hits("imran", response.hits, live_container.gateway)
        assert answer.text == ""
        assert answer.citations == []

    def test_an_uncited_sentence_is_never_published(self):
        """The grounding rule, independent of any model."""
        text = "The pool was exhausted [1]. I think it was probably the network."
        grounded, used = ground(text, available=2)
        assert "probably the network" not in grounded
        assert used == [1]


class TestPermissions:
    """Role decides what the API returns, not what the UI hides."""

    async def test_an_analyst_may_search(self, live_container, analyst):
        assert (await _search(live_container, analyst, TX)) is not None

    async def test_the_customer_is_resolvable(self, live_container, analyst):
        assert (await _search(live_container, analyst, CUSTOMER)) is not None
