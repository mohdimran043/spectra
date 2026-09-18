"""Recording what was searched, without letting it affect what was found.

History is written after the response is assembled, and dispatched as a
background task, so a slow or broken write cannot delay a search or change its
result. Every failure is logged and swallowed here deliberately: losing a
history row is a nuisance, failing a search because of one is a defect.
"""

from __future__ import annotations

from typing import Any

from spectra_config.logging import get_logger
from spectra_schemas import (
    PermissionContext,
    SearchHistoryEntry,
    SearchRequest,
    SearchResponse,
    new_id,
)

from .background import spawn

log = get_logger(__name__)

#: How many searches the page shows. Enough to recognise yesterday's work,
#: short enough to read without paging.
DEFAULT_HISTORY_LIMIT = 50
MAX_HISTORY_LIMIT = 200


def entry_for(
    request: SearchRequest,
    response: SearchResponse,
    ctx: PermissionContext,
    *,
    answered: bool = False,
) -> SearchHistoryEntry:
    """The row describing one completed search."""
    return SearchHistoryEntry(
        search_id=new_id("sh"),
        query=request.query,
        mode=request.mode,
        result_count=len(response.hits),
        candidates_screened=response.total_candidates,
        latency_ms=response.latency_ms,
        source_ids=list(request.filters.source_ids),
        answered=answered,
        user_id=ctx.user_id,
    )


def record(
    container: Any,
    request: SearchRequest,
    response: SearchResponse,
    ctx: PermissionContext,
    *,
    answered: bool = False,
) -> None:
    """Record a completed search in the background. Never raises."""
    repository = getattr(getattr(container, "storage", None), "repository", None)
    if repository is None:
        return
    entry = entry_for(request, response, ctx, answered=answered)

    async def write() -> None:
        try:
            await repository.record_search(entry)
        except Exception as exc:  # a lost history row must never fail a search
            log.warning("history.write_failed", query=entry.query, error=str(exc))

    spawn(write(), name=f"history:{entry.search_id}")
