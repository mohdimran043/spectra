"""Recording a search must never be able to break one.

History is a convenience: it tells an operator what has been asked and what came
back. Retrieval never reads it. So the rule enforced here is that the recording
path is entirely subordinate to the search path - a missing repository, a slow
write or a database error changes nothing about the response the caller already
received.

The second thing pinned here is that a search finding nothing is recorded as a
real outcome rather than skipped. "I searched and found nothing" is exactly the
row an operator needs to see.
"""

from __future__ import annotations

import asyncio

import pytest
from spectra_api import history
from spectra_schemas import (
    PermissionContext,
    Role,
    SearchFilters,
    SearchMode,
    SearchRequest,
    SearchResponse,
)

CTX = PermissionContext(user_id="u_1", role=Role.ANALYST)


def _request(query: str = "auth timeout", sources: list[str] | None = None) -> SearchRequest:
    return SearchRequest(
        query=query,
        mode=SearchMode.FAST,
        filters=SearchFilters(source_ids=sources or []),
    )


def _response(candidates: int = 80, latency: float = 191.2) -> SearchResponse:
    return SearchResponse(
        query="auth timeout",
        mode=SearchMode.FAST,
        hits=[],
        total_candidates=candidates,
        latency_ms=latency,
    )


class _Repository:
    """Records what it was asked to write, or fails on demand."""

    def __init__(self, *, explode: bool = False) -> None:
        self.written: list = []
        self._explode = explode

    async def record_search(self, entry) -> None:
        if self._explode:
            raise RuntimeError("database is down")
        self.written.append(entry)


class _Container:
    def __init__(self, repository) -> None:
        self.storage = type("Storage", (), {"repository": repository})()


class TestEntryFor:
    def test_it_carries_what_the_search_actually_did(self):
        # Arrange
        request = _request(sources=["src_docs", "src_media"])
        response = _response(candidates=80, latency=191.2)

        # Act
        entry = history.entry_for(request, response, CTX)

        # Assert
        assert entry.query == "auth timeout"
        assert entry.candidates_screened == 80
        assert entry.latency_ms == pytest.approx(191.2)
        assert entry.source_ids == ["src_docs", "src_media"]
        assert entry.user_id == "u_1"
        assert entry.search_id.startswith("sh_")

    def test_finding_nothing_is_a_recorded_outcome(self):
        entry = history.entry_for(_request(), _response(), CTX)
        assert entry.result_count == 0
        assert entry.found_nothing is True

    def test_an_unscoped_search_records_no_sources(self):
        """An empty filter means every source, and is stored as exactly that."""
        entry = history.entry_for(_request(sources=[]), _response(), CTX)
        assert entry.source_ids == []

    def test_answered_is_only_true_when_an_answer_was_published(self):
        assert history.entry_for(_request(), _response(), CTX).answered is False
        assert history.entry_for(_request(), _response(), CTX, answered=True).answered is True


class TestRecord:
    def test_it_writes_one_row(self):
        # Arrange
        repository = _Repository()

        # Act
        async def run() -> None:
            history.record(_Container(repository), _request(), _response(), CTX)
            await asyncio.sleep(0)  # let the background task run

        asyncio.run(run())

        # Assert
        assert len(repository.written) == 1
        assert repository.written[0].query == "auth timeout"

    def test_a_broken_write_never_raises(self):
        """The caller already has its results; a failed write must not surface."""
        repository = _Repository(explode=True)

        async def run() -> None:
            history.record(_Container(repository), _request(), _response(), CTX)
            await asyncio.sleep(0)

        asyncio.run(run())  # must not raise
        assert repository.written == []

    def test_no_repository_is_a_quiet_no_op(self):
        container = type("Container", (), {"storage": None})()
        history.record(container, _request(), _response(), CTX)  # must not raise

    def test_a_container_without_storage_is_a_quiet_no_op(self):
        history.record(object(), _request(), _response(), CTX)  # must not raise
