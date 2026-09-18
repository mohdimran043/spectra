"""Two-tier query understanding.

Tier 1 is a deterministic router built from explicit vocabulary: it classifies
intent, complexity, modality and time without a model, and it is the tier that
must be correct - the whole system stays useful with every model unloaded.
Tier 2 asks the fast brain to refine that classification under a strict JSON
schema, and its output is only ever *merged into* tier 1's, never trusted over
it for identifiers.
"""

from __future__ import annotations

from typing import Any

from spectra_config import Settings, get_settings
from spectra_config.logging import get_logger
from spectra_schemas import Modality, ModelRole, QueryIntent, QueryUnderstanding

from .context import ToolContext
from .lexicons import (
    AGGREGATION_TERMS,
    COMPARISON_TERMS,
    CONTRADICTION_TERMS,
    INVESTIGATION_TERMS,
    MEDIA_LOCATION_TERMS,
    contains_any,
    detect_ids,
    keywords,
    target_modalities,
    temporal_hint,
)
from .llm import structured, text_messages

log = get_logger(__name__)

RULE_ROUTER = "rule-router"
REFINED = "rule-router+fast_brain"

# Questions with three or more target modalities, or a causal/contradiction
# framing, cannot be answered by one retrieval pass - they are "complex".
COMPLEX_MODALITY_COUNT = 3

_FILLERS = (
    "can you ", "could you ", "please ", "i want to ", "i need to ", "show me ",
    "tell me ", "find me ", "help me ",
)

UNDERSTANDING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": [i.value for i in QueryIntent]},
        "complexity": {"type": "string", "enum": ["simple", "moderate", "complex"]},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "target_modalities": {
            "type": "array",
            "items": {"type": "string", "enum": [m.value for m in Modality]},
        },
        "temporal_hint": {"type": "string"},
        "rewritten": {"type": "string"},
        "explanation": {"type": "string"},
    },
    "required": ["intent", "complexity", "keywords"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You classify enterprise investigation queries. Reply with JSON only, matching the schema. "
    "Never invent identifiers. 'explanation' must be one sentence an analyst would understand."
)


class QueryUnderstandingService:
    """Classifies a question into an actionable :class:`QueryUnderstanding`."""

    def __init__(self, settings: Settings | None = None, gateway: Any | None = None) -> None:
        self._settings = settings or get_settings()
        self._gateway = gateway

    async def analyse(
        self, query: str, ctx: ToolContext | None = None, *, allow_llm: bool = True
    ) -> QueryUnderstanding:
        base = self.route(query)
        gateway = self._gateway or (ctx.services.gateway if ctx is not None else None)
        if not allow_llm or gateway is None:
            return base
        outcome = await structured(
            gateway,
            messages=text_messages(SYSTEM_PROMPT, _user_prompt(query, base)),
            schema=UNDERSTANDING_SCHEMA,
            role=ModelRole.FAST_BRAIN,
            max_tokens=384,
        )
        if not outcome.ok or outcome.data is None:
            log.info("understanding.rule_only", reason=outcome.reason)
            return base
        return _merge(base, outcome.data)

    # -- tier 1 -----------------------------------------------------------
    def route(self, query: str) -> QueryUnderstanding:
        """Deterministic classification - correct with no model available."""
        text = query.strip()
        ids = detect_ids(text)
        modalities = target_modalities(text)
        temporal = temporal_hint(text)
        intent = _classify(text, ids, modalities, temporal)
        complexity = _complexity(intent, ids, modalities)
        return QueryUnderstanding(
            original=text,
            rewritten=_rewrite(text),
            intent=intent,
            complexity=complexity,
            detected_ids=ids,
            target_modalities=modalities,
            temporal_hint=temporal,
            keywords=keywords(text),
            explanation=_explain(intent, ids, modalities, temporal),
            produced_by=RULE_ROUTER,
        )


def _classify(
    text: str, ids: list[str], modalities: list[Modality], temporal: str | None
) -> QueryIntent:
    if contains_any(text, CONTRADICTION_TERMS):
        return QueryIntent.CONTRADICTION
    if contains_any(text, INVESTIGATION_TERMS):
        return QueryIntent.INVESTIGATION
    if contains_any(text, COMPARISON_TERMS):
        return QueryIntent.COMPARISON
    if contains_any(text, MEDIA_LOCATION_TERMS) and _media_modalities(modalities):
        return QueryIntent.MEDIA_LOCATION
    if contains_any(text, AGGREGATION_TERMS):
        return QueryIntent.STRUCTURED_QUERY
    if temporal:
        return QueryIntent.TEMPORAL
    if ids:
        return QueryIntent.LOOKUP_BY_ID
    if _media_modalities(modalities):
        return QueryIntent.MEDIA_LOCATION
    return QueryIntent.SEMANTIC_SEARCH


def _media_modalities(modalities: list[Modality]) -> list[Modality]:
    return [m for m in modalities if m in (Modality.IMAGE, Modality.VIDEO, Modality.AUDIO)]


def _complexity(intent: QueryIntent, ids: list[str], modalities: list[Modality]) -> str:
    if intent in (QueryIntent.INVESTIGATION, QueryIntent.CONTRADICTION):
        return "complex"
    if len(modalities) >= COMPLEX_MODALITY_COUNT:
        return "complex"
    if intent in (QueryIntent.COMPARISON, QueryIntent.TEMPORAL, QueryIntent.MEDIA_LOCATION, QueryIntent.STRUCTURED_QUERY):
        return "moderate"
    if ids and modalities:
        return "moderate"
    return "simple"


def _rewrite(text: str) -> str:
    lowered = text.lstrip()
    for filler in _FILLERS:
        if lowered.lower().startswith(filler):
            lowered = lowered[len(filler) :]
    return lowered.strip().rstrip("?").strip() or text


def _explain(
    intent: QueryIntent, ids: list[str], modalities: list[Modality], temporal: str | None
) -> str:
    parts: list[str] = []
    if ids:
        parts.append(
            f"The query referenced {len(ids)} identifier(s) ({', '.join(ids[:3])}), "
            "so exact record lookup in the databases was selected first."
        )
    if modalities:
        names = ", ".join(m.value for m in modalities)
        parts.append(f"Wording pointed at {names} content, so those indexes were included.")
    if temporal:
        parts.append(f"A time reference ('{temporal}') was detected, so results are ordered on a timeline.")
    parts.append(_INTENT_REASON[intent])
    return " ".join(parts)


_INTENT_REASON: dict[QueryIntent, str] = {
    QueryIntent.LOOKUP_BY_ID: "The question asks for a specific record, so it runs as a direct lookup.",
    QueryIntent.STRUCTURED_QUERY: "The question asks for counts or aggregates, so the structured sources lead.",
    QueryIntent.SEMANTIC_SEARCH: "No identifier or aggregate was detected, so this runs as a meaning-based search.",
    QueryIntent.MEDIA_LOCATION: "The question asks where something appears, so media indexes lead.",
    QueryIntent.INVESTIGATION: "The question asks for a cause, so it runs as a full investigation with claims that get probed.",
    QueryIntent.TEMPORAL: "The question is about sequence, so evidence is assembled into a timeline.",
    QueryIntent.CONTRADICTION: "The question asks about conflicting information, so contradiction detection is mandatory.",
    QueryIntent.COMPARISON: "The question compares two things, so evidence is gathered for each side.",
}


def _user_prompt(query: str, base: QueryUnderstanding) -> str:
    return (
        f"Query: {query}\n"
        f"Rule-based classification: intent={base.intent.value}, complexity={base.complexity}, "
        f"modalities={[m.value for m in base.target_modalities]}, ids={base.detected_ids}\n"
        "Refine it if the rule-based reading is wrong; otherwise confirm it."
    )


def _merge(base: QueryUnderstanding, data: dict[str, Any]) -> QueryUnderstanding:
    """Merge model output into the rule result, keeping rule-detected identifiers."""
    update: dict[str, Any] = {"produced_by": REFINED}
    intent = _enum(QueryIntent, data.get("intent"))
    if intent is not None:
        update["intent"] = intent
    if data.get("complexity") in ("simple", "moderate", "complex"):
        update["complexity"] = data["complexity"]
    modalities = [m for m in (_enum(Modality, v) for v in data.get("target_modalities") or []) if m]
    if modalities:
        update["target_modalities"] = modalities
    extra = [k for k in data.get("keywords") or [] if isinstance(k, str)]
    if extra:
        merged = list(base.keywords)
        merged.extend(k.lower() for k in extra if k.lower() not in merged)
        update["keywords"] = merged[:16]
    if isinstance(data.get("temporal_hint"), str) and data["temporal_hint"].strip():
        update["temporal_hint"] = data["temporal_hint"].strip()
    if isinstance(data.get("rewritten"), str) and data["rewritten"].strip():
        update["rewritten"] = data["rewritten"].strip()
    if isinstance(data.get("explanation"), str) and data["explanation"].strip():
        update["explanation"] = f"{base.explanation} {data['explanation'].strip()}"
    return base.model_copy(update=update)


def _enum(enum_type: Any, value: Any) -> Any | None:
    if not isinstance(value, str):
        return None
    try:
        return enum_type(value)
    except ValueError:
        return None
