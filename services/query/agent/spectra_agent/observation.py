"""Turning tool results into investigation state.

The execution engine handles evidence; everything else a tool can return -
entities, contradictions, timeline events, application links, verification -
is absorbed here, so the loop itself stays about *deciding what to do next*.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from spectra_config.logging import get_logger
from spectra_schemas import (
    ApplicationLink,
    Contradiction,
    InvestigationState,
    TimelineEvent,
    ToolResult,
    VerificationResult,
)

from . import state_ops

log = get_logger(__name__)


def observe(state: InvestigationState, results: Sequence[ToolResult]) -> InvestigationState:
    """Fold every non-evidence payload of ``results`` into a NEW state."""
    for result in results:
        if not result.ok or not result.data:
            continue
        state = _entities(state, result)
        state = _contradictions(state, result)
        state = _timeline(state, result)
        state = _links(state, result)
        state = _verification(state, result)
    return state


def _entities(state: InvestigationState, result: ToolResult) -> InvestigationState:
    found: list[str] = []
    if result.tool == "resolve_entity" and result.data.get("entity_id"):
        found.append(str(result.data["entity_id"]))
    for entity in result.data.get("entities") or []:
        if isinstance(entity, dict) and entity.get("entity_id"):
            found.append(str(entity["entity_id"]))
    found.extend(str(identifier) for identifier in result.data.get("entity_ids") or [])
    merged = list(state.entities)
    merged.extend(entity for entity in found if entity not in merged)
    return state_ops.touch(state, entities=merged) if merged != state.entities else state


def _contradictions(state: InvestigationState, result: ToolResult) -> InvestigationState:
    known = {c.contradiction_id for c in state.contradictions}
    found = [c for c in validate(Contradiction, result.data.get("contradictions") or []) if c.contradiction_id not in known]
    if not found:
        return state
    metrics = state.metrics.model_copy(update={"contradictions": state.metrics.contradictions + len(found)})
    return state_ops.touch(state, contradictions=[*state.contradictions, *found], metrics=metrics)


def _timeline(state: InvestigationState, result: ToolResult) -> InvestigationState:
    events = validate(TimelineEvent, result.data.get("events") or [])
    known = {event.event_id for event in state.timeline}
    fresh = [event for event in events if event.event_id not in known]
    return state_ops.touch(state, timeline=[*state.timeline, *fresh]) if fresh else state


def _links(state: InvestigationState, result: ToolResult) -> InvestigationState:
    links = validate(ApplicationLink, result.data.get("links") or [])
    known = {link.record_id for link in state.application_links}
    fresh = [link for link in links if link.record_id not in known]
    return state_ops.touch(state, application_links=[*state.application_links, *fresh]) if fresh else state


def _verification(state: InvestigationState, result: ToolResult) -> InvestigationState:
    payload = result.data.get("verification")
    if not isinstance(payload, dict):
        return state
    verification = validate(VerificationResult, [payload])
    return state_ops.touch(state, verification=verification[0]) if verification else state


def validate(model: Any, payloads: Sequence[Any]) -> list[Any]:
    """Re-validate peer payloads; drift is logged and discarded, never crashes."""
    out: list[Any] = []
    for payload in payloads:
        if isinstance(payload, model):
            out.append(payload)
            continue
        try:
            out.append(model.model_validate(payload))
        except Exception as exc:
            log.warning("observe.payload_discarded", model=model.__name__, error=str(exc))
    return out
