"""Server-Sent Events for live agent traces.

Emits `trace`, `status`, `complete` and `error` events plus a heartbeat, so a
proxy never closes a long investigation.  Reconnects replay from `Last-Event-ID`.

Only action summaries cross this boundary - model chain-of-thought never does.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Header, Request
from spectra_config.logging import get_logger
from spectra_schemas import InvestigationStatus
from sse_starlette.sse import EventSourceResponse

from ..dependencies import Container, Ctx, service_or_503
from ..errors import NotFound

router = APIRouter(tags=["stream"])
log = get_logger(__name__)

HEARTBEAT_SECONDS = 15.0
TERMINAL = {InvestigationStatus.COMPLETED, InvestigationStatus.FAILED}
MAX_STREAM_SECONDS = 900.0


def _event(name: str, payload: dict[str, Any], event_id: str | None = None) -> dict[str, str]:
    out = {"event": name, "data": json.dumps(payload, default=str)}
    if event_id:
        out["id"] = event_id
    return out


@router.get("/stream/investigation/{investigation_id}")
async def stream_investigation(
    investigation_id: str,
    request: Request,
    container: Container,
    ctx: Ctx,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
):
    service = service_or_503(container, "investigations")
    broker = container.trace_broker
    if broker is None:
        raise NotFound("trace streaming is unavailable in this deployment")

    repository = container.storage.repository
    state = await repository.get_investigation(investigation_id)
    if state is None:
        raise NotFound(f"unknown investigation: {investigation_id!r}")

    async def generator() -> AsyncIterator[dict[str, str]]:
        # Subscribe *before* replaying, so a step emitted during replay is queued
        # rather than lost.
        subscription = broker.subscribe(investigation_id)
        seen: set[int] = set()
        resume_from = int(last_event_id) if (last_event_id or "").isdigit() else -1

        try:
            for step in state.trace:
                if step.sequence > resume_from:
                    seen.add(step.sequence)
                    yield _event("trace", step.model_dump(mode="json"), str(step.sequence))

            yield _event("status", {"status": state.status.value, "investigation_id": investigation_id})

            deadline = asyncio.get_running_loop().time() + MAX_STREAM_SECONDS
            while True:
                if await request.is_disconnected():
                    return
                if asyncio.get_running_loop().time() > deadline:
                    yield _event("error", {"error": "stream timed out", "recoverable": True})
                    return
                try:
                    step = await asyncio.wait_for(subscription.__anext__(), timeout=HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    if await _is_terminal(repository, investigation_id):
                        break
                    yield {"event": "ping", "data": "keep-alive"}
                    continue
                except StopAsyncIteration:
                    break

                if step.sequence in seen:
                    continue
                seen.add(step.sequence)
                yield _event("trace", step.model_dump(mode="json"), str(step.sequence))
        finally:
            await subscription.aclose()

        final = await repository.get_investigation(investigation_id)
        if final is None:
            yield _event("error", {"error": "investigation disappeared", "recoverable": False})
            return
        yield _event("status", {"status": final.status.value, "investigation_id": investigation_id})
        yield _event("complete", service.to_answer(final).model_dump(mode="json"))

    return EventSourceResponse(generator(), ping=int(HEARTBEAT_SECONDS))


async def _is_terminal(repository: Any, investigation_id: str) -> bool:
    current = await repository.get_investigation(investigation_id)
    return current is not None and current.status in TERMINAL
