"""User-facing explanation of *why* SPECTRA searched what it searched.

This is an action-level account - which sources were chosen, which were skipped
and why.  It never contains model reasoning: only decisions, tools and evidence.
"""

from __future__ import annotations

from spectra_schemas import InvestigationState, Modality, QueryExplanation, QueryIntent

TOOL_LABELS: dict[str, str] = {
    "search_documents": "Document Search",
    "search_images": "Image Search",
    "search_videos": "Video Search",
    "search_audio": "Audio Search",
    "query_database": "Database Search",
    "get_database_schema": "Database Schema",
    "get_database_record": "Database Record",
    "resolve_entity": "Entity Resolution",
    "search_entities": "Entity Search",
    "search_graph": "Knowledge Graph",
    "expand_graph": "Knowledge Graph Expansion",
    "get_evidence": "Evidence Ledger",
    "get_source_metadata": "Source Catalogue",
    "get_document_page": "Document Page",
    "get_video_timestamp": "Video Timestamp",
    "get_image": "Image Store",
    "verify_claim": "Verifier",
    "search_supporting_evidence": "Corroboration Search",
    "search_disconfirming_evidence": "Disproof Search",
    "detect_contradictions": "Contradiction Radar",
    "build_timeline": "Timeline Builder",
    "open_application_record": "Application Deep Link",
}

MODALITY_TOOLS: dict[Modality, str] = {
    Modality.DOCUMENT: "search_documents",
    Modality.IMAGE: "search_images",
    Modality.VIDEO: "search_videos",
    Modality.AUDIO: "search_audio",
    Modality.DATABASE: "query_database",
}

_INTENT_REASONS: dict[QueryIntent, str] = {
    QueryIntent.LOOKUP_BY_ID: "The query asked for one record, so exact lookup ran before any semantic search.",
    QueryIntent.INVESTIGATION: "The query asked for a cause, so competing hypotheses were generated and probed.",
    QueryIntent.CONTRADICTION: "The query asked about conflicting information, so contradiction detection was mandatory.",
    QueryIntent.TEMPORAL: "The query was about sequence, so dated evidence was assembled into a timeline.",
    QueryIntent.MEDIA_LOCATION: "The query asked where something appears, so media indexes led the search.",
    QueryIntent.STRUCTURED_QUERY: "The query asked for aggregates, so structured sources led the search.",
    QueryIntent.COMPARISON: "The query compared two subjects, so evidence was gathered for each side.",
    QueryIntent.SEMANTIC_SEARCH: "No identifier was present, so meaning-based retrieval led the search.",
}


class ExplanationBuilder:
    """Builds the 'why these sources' panel."""

    def build(self, state: InvestigationState) -> QueryExplanation:
        used = [call.tool for call in state.tool_history]
        reasons = self._reasons(state, used)
        selected = [TOOL_LABELS.get(tool, tool) for tool in _ordered_unique(used)]
        return QueryExplanation(
            reasons=reasons,
            sources_selected=selected,
            sources_skipped=self._skipped(state, set(used)),
        )

    def _reasons(self, state: InvestigationState, used: list[str]) -> list[str]:
        understanding = state.understanding
        reasons: list[str] = []
        if understanding is None:
            return ["The query was answered without a classification step."]
        if understanding.detected_ids and "query_database" in used:
            reasons.append(
                f"The query referenced an identifier ({understanding.detected_ids[0]}), "
                "so Database Search was selected first."
            )
        for modality in understanding.target_modalities:
            tool = MODALITY_TOOLS.get(modality)
            if tool and tool in used:
                reasons.append(
                    f"The wording pointed at {modality.value} content, so {TOOL_LABELS[tool]} was included."
                )
        if understanding.temporal_hint:
            reasons.append(
                f"A time reference ('{understanding.temporal_hint}') was detected, so evidence was ordered on a timeline."
            )
        reasons.append(_INTENT_REASONS.get(understanding.intent, ""))
        if state.budget.exhausted_reason:
            reasons.append(f"The search stopped early: {state.budget.exhausted_reason}.")
        reasons.extend(f"Reduced capability: {reason}." for reason in state.degraded_reasons)
        return [reason for reason in reasons if reason]

    def _skipped(self, state: InvestigationState, used: set[str]) -> list[dict[str, str]]:
        skipped: list[dict[str, str]] = []
        for availability in state.agent_availability:
            if availability.enabled and availability.ready:
                continue
            skipped.append(
                {
                    "source": availability.name,
                    "reason": availability.reason or "agent disabled in this deployment",
                    "alternatives": ", ".join(availability.alternatives) or "none",
                }
            )
        named = {entry["source"] for entry in skipped}
        for modality, tool in MODALITY_TOOLS.items():
            label = TOOL_LABELS[tool]
            if tool in used or label in named:
                continue
            skipped.append({"source": label, "reason": _not_selected_reason(state, modality), "alternatives": ""})
        return skipped


def _not_selected_reason(state: InvestigationState, modality: Modality) -> str:
    if state.budget.exhausted_reason:
        return f"not reached before the budget stopped the search ({state.budget.exhausted_reason})"
    understanding = state.understanding
    if understanding and understanding.target_modalities and modality not in understanding.target_modalities:
        return "the query contained no signal pointing at this modality"
    return "no candidates were expected for this query shape"


def _ordered_unique(values: list[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen
