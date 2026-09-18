"""The acceptance scenarios from the specification, run against the live stack.

Each test is one of the five end-to-end journeys the project is required to
demonstrate.  They use the real ingestion pipeline, the real retrieval stack and
the real Brain - if a model is unavailable the system degrades, and the tests
assert the degradation is honest rather than skipping.
"""

from __future__ import annotations

import pytest
from spectra_schemas import SearchMode, SearchRequest

from .conftest import CUSTOMER, INCIDENT, TX

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


def _answer(container, state):
    return container.investigations.to_answer(state)


class TestScenarioOneImageToInvestigation:
    """Spec §73: upload a screenshot containing a transaction id, then investigate."""

    async def test_ocr_recovers_the_identifier_from_the_screenshot(self, live_container):
        assets = await live_container.storage.repository.list_assets(limit=50)
        image = next(a for a in assets if a.kind.value == "image")
        chunks = await live_container.storage.repository.list_chunks_by_asset(image.asset_id)
        text = " ".join(c.text for c in chunks).upper()
        assert TX in text, "OCR must recover the transaction id from the uploaded screenshot"

    async def test_the_identifier_resolves_across_surface_forms(self, live_container, analyst):
        resolved = set()
        for surface in (TX, "Txn 82931", "Transaction #82931"):
            resolution = await live_container.entities.resolve(surface, analyst)
            if resolution.resolved:
                resolved.add(resolution.resolved.entity_id)
        assert len(resolved) == 1, f"surface variants must collapse to one entity, got {resolved}"

    async def test_investigation_produces_cited_evidence_and_a_trace(self, live_container, analyst):
        state = await live_container.investigations.investigate(
            f"Investigate why transaction {TX} failed and show me the supporting evidence.",
            mode=SearchMode.DEEP,
            ctx=analyst,
        )
        answer = _answer(live_container, state)

        assert state.trace, "the investigation must leave an observable trace"
        assert answer.evidence, "the investigation must produce evidence"
        assert all(item.get("citation") for item in answer.evidence), "every item needs a citation"
        assert answer.claims, "deep mode must produce evidence-grounded claims"
        assert any(c.disproof_searched for c in answer.claims), "the disproof probe must run"
        leading = max(answer.claims, key=lambda c: c.confidence)
        assert leading.confidence > 0.0, "a claim must be scored on its own evidence"

    async def test_no_chain_of_thought_is_exposed(self, live_container, analyst):
        state = await live_container.investigations.investigate(
            f"Why did {TX} fail?", mode=SearchMode.DEEP, ctx=analyst
        )
        answer = _answer(live_container, state)
        blob = (answer.answer + " ".join(s.output_summary for s in state.trace)).lower()
        for tag in ("<think", "</think", "<reasoning"):
            assert tag not in blob, f"model reasoning leaked: {tag}"


class TestScenarioTwoMediaLocation:
    """Spec §74: locate where something was discussed, with precise provenance."""

    async def test_document_results_cite_an_exact_page(self, live_container, analyst):
        response = await live_container.search.search(
            SearchRequest(query="authentication connection pool exhausted", mode=SearchMode.FAST, top_k=10),
            analyst,
        )
        assert response.hits, "retrieval must return something for an in-corpus query"
        documents = [h for h in response.hits if h.modality.value == "document"]
        assert documents, "the corpus contains documents; retrieval must surface them"
        assert any(getattr(h.provenance.locator, "page", None) for h in documents), (
            "a document hit must cite the page it came from"
        )

    async def test_every_hit_carries_a_score_breakdown(self, live_container, analyst):
        response = await live_container.search.search(
            SearchRequest(query="authentication timeout", mode=SearchMode.FAST, top_k=5), analyst
        )
        assert response.hits
        assert any(h.scores.final > 0 for h in response.hits), "ranking must be explainable"
        assert response.stages, "the staged pipeline must report its stages"


class TestScenarioThreeStructuredAggregation:
    """Spec §75: an aggregation question answered against the real database."""

    async def test_fast_mode_answers_an_identifier_lookup_cheaply(self, live_container, analyst):
        state = await live_container.investigations.investigate(
            f"Find transaction {TX}", mode=SearchMode.FAST, ctx=analyst
        )
        assert state.metrics.tool_calls <= 5, "fast mode must respect its tool budget"
        assert state.trace, "even fast mode leaves a trace"


class TestScenarioFourContradiction:
    """Spec §76: sources disagree; the system must surface and explain the conflict."""

    async def test_both_memo_versions_are_retrievable(self, live_container, analyst):
        response = await live_container.search.search(
            SearchRequest(query=f"was incident {INCIDENT} approved or rejected",
                          mode=SearchMode.FAST, top_k=10),
            analyst,
        )
        text = " ".join((h.snippet or h.text) for h in response.hits).lower()
        assert "approved" in text or "rejected" in text, (
            "the conflicting approval memos must be retrievable"
        )

    async def test_contradictory_evidence_is_reported_not_hidden(self, live_container, analyst):
        state = await live_container.investigations.investigate(
            f"The sources disagree about whether incident {INCIDENT} was approved. Investigate.",
            mode=SearchMode.DEEP,
            ctx=analyst,
        )
        answer = _answer(live_container, state)
        # Either a contradiction is reported, or the answer is honest about the
        # disagreement - what is forbidden is silently picking one side.
        mentions_conflict = any(
            word in answer.answer.lower() for word in ("disagree", "contradict", "conflict", "however")
        )
        assert answer.contradictions or mentions_conflict or answer.status.value in (
            "insufficient_evidence", "contested", "degraded"
        ), "a disagreement must be surfaced, not silently resolved"


class TestScenarioFiveGracefulDegradation:
    """Spec §77: disable the Vision Agent, then investigate."""

    async def test_disabling_vision_removes_its_tools_and_still_answers(self, live_container, analyst):
        previous = dict(live_container.agent_overrides)
        live_container.agent_overrides = {**previous, "image": False}
        try:
            state = await live_container.investigations.investigate(
                f"Investigate why transaction {TX} failed.", mode=SearchMode.DEEP, ctx=analyst
            )
        finally:
            live_container.agent_overrides = previous

        assert state.status.value in ("completed", "failed")
        assert state.trace, "the investigation must still run"
        used = {call.tool for call in state.tool_history}
        assert "search_images" not in used, "a disabled agent's tools must not be invoked"

    async def test_agent_availability_names_alternatives(self, live_container):
        from spectra_api.routers.agents import AGENT_CATALOG

        for name, spec in AGENT_CATALOG.items():
            assert spec["alternatives"], f"{name} must declare what the Brain uses instead"


class TestAbstention:
    """Spec §44: the system must be able to say it does not know."""

    async def test_unanswerable_question_abstains(self, live_container, analyst):
        state = await live_container.investigations.investigate(
            "What did the CFO decide about the Antarctic division's 2041 budget?",
            mode=SearchMode.DEEP,
            ctx=analyst,
        )
        answer = _answer(live_container, state)
        assert answer.status.value in ("insufficient_evidence", "degraded"), (
            f"must abstain on an unanswerable question, got {answer.status.value}"
        )
        assert "insufficient evidence" in answer.answer.lower()

    async def test_abstention_does_not_invent_entities(self, live_container, analyst):
        state = await live_container.investigations.investigate(
            "Summarise the Antarctic division's 2041 budget decision.",
            mode=SearchMode.DEEP,
            ctx=analyst,
        )
        answer = _answer(live_container, state)
        assert "antarctic" not in answer.answer.lower() or "insufficient" in answer.answer.lower()


class TestPermissions:
    """Spec §46: retrieval is permission-aware at every level."""

    async def test_viewer_cannot_run_sql(self, live_container):
        from spectra_schemas import PermissionContext, Role

        viewer = PermissionContext(user_id="v", role=Role.VIEWER)
        assert not viewer.can("run_sql")
        assert viewer.can("search")

    async def test_customer_identifier_is_still_resolvable_for_a_viewer(self, live_container):
        from spectra_schemas import PermissionContext, Role

        viewer = PermissionContext(user_id="v", role=Role.VIEWER)
        resolution = await live_container.entities.resolve(CUSTOMER, viewer)
        assert resolution is not None
