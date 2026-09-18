"""Tool selection: what to call first, and what the evidence gap says to call next.

The planner is pure - state in, planned calls out - so the loop's decisions are
testable on their own and appear verbatim in the trace.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from typing import Any

from spectra_schemas import (
    EntityType,
    InvestigationState,
    Modality,
    QueryIntent,
    QueryUnderstanding,
    SearchMode,
)

from .thresholds import MIN_SUPPORTING_ITEMS

# A deep iteration fans out at most four calls: enough to cover a modality
# gap plus a corroboration probe, few enough to leave budget for the next one.
MAX_CALLS_PER_ITERATION = 4
FAST_TOP_K = 5
DEEP_TOP_K = 10

MODALITY_TOOL: dict[Modality, str] = {
    Modality.DOCUMENT: "search_documents",
    Modality.IMAGE: "search_images",
    Modality.VIDEO: "search_videos",
    Modality.AUDIO: "search_audio",
}

ENTITY_TYPE_HINTS: tuple[tuple[str, EntityType], ...] = (
    ("transaction", EntityType.TRANSACTION),
    ("payment", EntityType.TRANSACTION),
    ("order", EntityType.TRANSACTION),
    ("invoice", EntityType.TRANSACTION),
    ("customer", EntityType.CUSTOMER),
    ("account", EntityType.CUSTOMER),
    ("client", EntityType.CUSTOMER),
    ("incident", EntityType.INCIDENT),
    ("ticket", EntityType.INCIDENT),
    ("outage", EntityType.INCIDENT),
    ("asset", EntityType.ASSET),
    ("device", EntityType.ASSET),
    ("service", EntityType.SERVICE),
    ("system", EntityType.SERVICE),
    ("employee", EntityType.PERSON),
    ("person", EntityType.PERSON),
)


@dataclass(frozen=True)
class PlannedCall:
    """One intended tool call plus the reason it was chosen."""

    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def key(self) -> str:
        return f"{self.tool}:{json.dumps(self.args, sort_keys=True, default=str)}"

    def describe(self) -> str:
        return f"{self.tool} - {self.reason}"


def guess_entity_type(understanding: QueryUnderstanding) -> str:
    text = f"{understanding.original} {' '.join(understanding.keywords)}".lower()
    for term, entity_type in ENTITY_TYPE_HINTS:
        if term in text:
            return entity_type.value
    return EntityType.OTHER.value


def initial_plan(
    understanding: QueryUnderstanding, available: Collection[str], mode: SearchMode
) -> list[PlannedCall]:
    """The first round of calls implied by the query classification."""
    query = understanding.rewritten or understanding.original
    top_k = FAST_TOP_K if mode is SearchMode.FAST else DEEP_TOP_K
    calls: list[PlannedCall] = []
    ids = understanding.detected_ids

    if ids:
        entity_type = guess_entity_type(understanding)
        calls.append(
            PlannedCall(
                "query_database",
                {"entity_type": entity_type, "value": ids[0]},
                f"the query names the identifier {ids[0]}, so the systems of record are checked first",
            )
        )
        calls.append(
            PlannedCall(
                "resolve_entity",
                {"surface": ids[0], "entity_type": entity_type},
                "resolving the identifier links records across sources",
            )
        )

    if mode is SearchMode.FAST:
        if not ids:
            calls.append(
                PlannedCall(
                    "search_documents",
                    {"query": query, "top_k": top_k},
                    "no identifier was present, so fast mode falls back to document retrieval",
                )
            )
        return _filter(calls, available, limit=len(calls))

    if understanding.intent is QueryIntent.STRUCTURED_QUERY:
        calls.append(
            PlannedCall(
                "get_database_schema",
                {},
                "the query asks for aggregates, so the schema is read before querying",
            )
        )

    calls.append(
        PlannedCall(
            "search_documents",
            {"query": query, "top_k": top_k},
            "documents carry the narrative context behind the records",
        )
    )
    for modality in understanding.target_modalities:
        tool = MODALITY_TOOL.get(modality)
        if tool and tool != "search_documents":
            calls.append(
                PlannedCall(
                    tool,
                    {"query": query, "top_k": top_k},
                    f"the wording points at {modality.value} content",
                )
            )
    if ids or understanding.intent is QueryIntent.INVESTIGATION:
        calls.append(
            PlannedCall(
                "search_graph",
                {"query": query},
                "the entity graph shows what else the subject is connected to",
            )
        )
    return _filter(calls, available, limit=MAX_CALLS_PER_ITERATION + 2)


def replan(state: InvestigationState, available: Collection[str]) -> list[PlannedCall]:
    """Close the biggest evidence gap that is still closable."""
    understanding = state.understanding
    if understanding is None:
        return []
    query = understanding.rewritten or understanding.original
    done = {_key(call.tool, call.arguments) for call in state.tool_history}
    used_modalities = {item.modality for item in state.evidence.items}
    calls: list[PlannedCall] = []

    if understanding.detected_ids and Modality.DATABASE not in used_modalities:
        calls.append(
            PlannedCall(
                "query_database",
                {"entity_type": guess_entity_type(understanding), "value": understanding.detected_ids[0]},
                "no system-of-record evidence has been gathered yet",
            )
        )

    leader = state.leading_hypothesis()
    if leader is not None and len(leader.supporting_evidence) < MIN_SUPPORTING_ITEMS:
        calls.append(
            PlannedCall(
                "search_supporting_evidence",
                {"claim": leader.description, "top_k": DEEP_TOP_K},
                f"{leader.hypothesis_id} needs independent corroboration before it can be asserted",
            )
        )

    for modality, tool in MODALITY_TOOL.items():
        if modality in used_modalities or tool not in available:
            continue
        calls.append(
            PlannedCall(
                tool,
                {"query": query, "top_k": DEEP_TOP_K},
                f"no {modality.value} evidence has been retrieved yet, so corroboration may be missing",
            )
        )

    if len(state.evidence.items) >= 2 and not state.contradictions:
        calls.append(
            PlannedCall(
                "detect_contradictions",
                {},
                "gathered evidence has not yet been checked for conflicts",
            )
        )

    if understanding.temporal_hint and not state.timeline:
        calls.append(
            PlannedCall("build_timeline", {}, "the question is about sequence, so evidence is ordered in time")
        )

    fresh = [call for call in calls if call.key() not in done]
    return _filter(fresh, available, limit=MAX_CALLS_PER_ITERATION)


def _filter(calls: Sequence[PlannedCall], available: Collection[str], limit: int) -> list[PlannedCall]:
    seen: set[str] = set()
    kept: list[PlannedCall] = []
    for call in calls:
        if call.tool not in available or call.key() in seen:
            continue
        seen.add(call.key())
        kept.append(call)
        if len(kept) >= limit:
            break
    return kept


def _key(tool: str, args: dict[str, Any]) -> str:
    return f"{tool}:{json.dumps(args, sort_keys=True, default=str)}"
