"""The evidence graph: entities, assets, evidence, hypotheses and time order.

Written INCREMENTALLY - every ingestion step and every investigation step adds
the nodes and edges it just learned about, so there is never a batch rebuild and
the graph is queryable mid-investigation.  Labels and relationship types are a
closed vocabulary; anything outside it is rejected loudly rather than silently
creating a parallel schema.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import Enum
from typing import Any

from spectra_config.logging import get_logger
from spectra_schemas import (
    ApplicationLink,
    CanonicalEntity,
    EntityType,
    EvidenceItem,
    EvidenceStance,
    GraphEdge,
    GraphNode,
    GraphView,
    Hypothesis,
    Modality,
    TimelineEvent,
)
from spectra_storage.interfaces import GraphStore

from .locators import asset_node_key, unit_identifier
from .text_utils import MAX_SUMMARY_CHARS, truncate

log = get_logger(__name__)

NODE_LABELS: frozenset[str] = frozenset(
    {
        "Person",
        "Customer",
        "Transaction",
        "Incident",
        "Event",
        "Document",
        "Page",
        "Image",
        "Video",
        "Scene",
        "Frame",
        "Audio",
        "AudioSegment",
        "DatabaseRecord",
        "ApplicationRecord",
        "Hypothesis",
        "Claim",
        "Evidence",
    }
)

EDGE_TYPES: frozenset[str] = frozenset(
    {
        "MENTIONS",
        "REFERS_TO",
        "SAME_ENTITY",
        "SUPPORTS",
        "CONTRADICTS",
        "CAUSED_BY",
        "PRECEDES",
        "SUPERSEDES",
        "DERIVED_FROM",
        "BELONGS_TO",
        "EVIDENCE_FOR",
        "OPENED_AS",
    }
)

# Entity types outside the closed node vocabulary (service, organisation,
# location, asset, other) are stored as ApplicationRecord - "a record of a thing
# in the enterprise" - with entity_type kept as a property so nothing is lost.
DEFAULT_ENTITY_LABEL = "ApplicationRecord"
ENTITY_LABELS: Mapping[EntityType, str] = {
    EntityType.PERSON: "Person",
    EntityType.CUSTOMER: "Customer",
    EntityType.TRANSACTION: "Transaction",
    EntityType.INCIDENT: "Incident",
    EntityType.EVENT: "Event",
}

ASSET_LABELS: Mapping[Modality, str] = {
    Modality.DOCUMENT: "Document",
    Modality.IMAGE: "Image",
    Modality.VIDEO: "Video",
    Modality.AUDIO: "Audio",
    Modality.DATABASE: "DatabaseRecord",
    Modality.EXTERNAL: "ApplicationRecord",
    Modality.GRAPH: "ApplicationRecord",
}

# Label for the retrievable unit inside an asset, per locator kind.
UNIT_LABELS: Mapping[str, str] = {
    "document": "Page",
    "video": "Scene",
    "audio": "AudioSegment",
    "image": "Image",
    "database": "DatabaseRecord",
    "external": "ApplicationRecord",
}

STANCE_EDGES: Mapping[EvidenceStance, str] = {
    EvidenceStance.SUPPORTING: "SUPPORTS",
    EvidenceStance.CONTRADICTING: "CONTRADICTS",
    EvidenceStance.NEUTRAL: "EVIDENCE_FOR",
}

# Expansion ceilings: an investigation view must stay small enough to render.
DEFAULT_NEIGHBOUR_LIMIT = 100
MAX_INVESTIGATION_ANCHORS = 50


class GraphVocabularyError(ValueError):
    """Raised when a caller asks for a label or relationship type we do not allow."""


def validate_label(label: str) -> str:
    if label not in NODE_LABELS:
        raise GraphVocabularyError(f"unknown node label {label!r}; allowed: {sorted(NODE_LABELS)}")
    return label


def validate_edge_type(edge_type: str) -> str:
    if edge_type not in EDGE_TYPES:
        raise GraphVocabularyError(
            f"unknown relationship type {edge_type!r}; allowed: {sorted(EDGE_TYPES)}"
        )
    return edge_type


class EvidenceGraph:
    """Incremental writer / reader over the configured ``GraphStore``."""

    def __init__(self, store: GraphStore) -> None:
        self._store = store

    # -- writes -----------------------------------------------------------
    async def add_entity(self, entity: CanonicalEntity, *, investigation_id: str | None = None) -> str:
        label = ENTITY_LABELS.get(entity.entity_type, DEFAULT_ENTITY_LABEL)
        properties = {
            "canonical_name": entity.canonical_name,
            "entity_type": entity.entity_type.value,
            "aliases": list(entity.aliases),
            "confidence": entity.confidence,
            "source_ids": list(entity.source_ids),
            "mention_count": entity.mention_count,
            "record_id": entity.attributes.get("record_id", entity.canonical_name),
            "investigation_id": investigation_id,
        }
        await self._upsert_node(entity.entity_id, label, properties)
        return entity.entity_id

    async def add_asset_node(
        self,
        asset_id: str,
        modality: Modality,
        *,
        title: str | None = None,
        properties: Mapping[str, Any] | None = None,
    ) -> str:
        label = ASSET_LABELS.get(modality, DEFAULT_ENTITY_LABEL)
        payload = {"title": title, "modality": modality.value, **dict(properties or {})}
        await self._upsert_node(asset_id, label, payload)
        return asset_id

    async def add_chunk_mention(
        self,
        *,
        chunk_id: str,
        asset_id: str,
        modality: Modality,
        entity_id: str,
        provenance: Any | None = None,
        surface: str = "",
        confidence: float = 1.0,
    ) -> str:
        """Record ``unit MENTIONS entity`` and ``asset REFERS_TO entity``."""
        locator_kind = getattr(getattr(provenance, "locator", None), "kind", modality.value)
        unit_id = unit_identifier(provenance, chunk_id) if provenance is not None else chunk_id
        unit_label = UNIT_LABELS.get(str(locator_kind), ASSET_LABELS.get(modality, DEFAULT_ENTITY_LABEL))
        await self.add_asset_node(asset_id, modality)
        await self._upsert_node(unit_id, unit_label, {"chunk_id": chunk_id, "asset_id": asset_id})
        await self._upsert_edge("BELONGS_TO", unit_id, asset_id, {})
        await self._upsert_edge("MENTIONS", unit_id, entity_id, {"surface": surface, "confidence": confidence})
        await self._upsert_edge("REFERS_TO", asset_id, entity_id, {"confidence": confidence})
        return unit_id

    async def add_evidence(self, item: EvidenceItem, *, investigation_id: str | None = None) -> str:
        asset = asset_node_key(item.provenance)
        properties = {
            "kind": item.kind.value,
            "modality": item.modality.value,
            "summary": truncate(item.summary, MAX_SUMMARY_CHARS),
            "citation": item.citation(),
            "source_id": item.provenance.source_id,
            "object_uri": item.provenance.object_uri,
            "locator": item.provenance.locator.model_dump(mode="json"),
            "relevance": item.relevance,
            "reliability": item.reliability,
            "reliability_reason": item.reliability_reason,
            "weight": item.weight,
            "stance": item.stance.value,
            "occurred_at": item.occurred_at,
            "retrieved_by": item.retrieved_by,
            "entities": list(item.entities),
            "investigation_id": investigation_id,
            # Full item kept verbatim so the ledger can rehydrate it losslessly.
            "payload": item.model_dump(mode="json"),
        }
        await self._upsert_node(item.evidence_id, "Evidence", properties)
        await self.add_asset_node(asset, item.modality)
        await self._upsert_edge("DERIVED_FROM", item.evidence_id, asset, {})
        for entity in item.entities:
            await self._upsert_edge("REFERS_TO", item.evidence_id, entity, {})
        for hypothesis_id in item.hypothesis_ids:
            await self.link_evidence_to_hypothesis(item.evidence_id, hypothesis_id, item.stance)
        return item.evidence_id

    async def add_hypothesis(self, hypothesis: Hypothesis, *, investigation_id: str | None = None) -> str:
        properties = {
            "description": hypothesis.description,
            "status": hypothesis.status.value,
            "confidence": hypothesis.confidence,
            "prior": hypothesis.prior,
            "verified": hypothesis.verified,
            "investigation_id": investigation_id,
        }
        await self._upsert_node(hypothesis.hypothesis_id, "Hypothesis", properties)
        return hypothesis.hypothesis_id

    async def link_evidence_to_hypothesis(
        self, evidence_id: str, hypothesis_id: str, stance: EvidenceStance
    ) -> str:
        edge_type = STANCE_EDGES[stance]
        return await self._upsert_edge(edge_type, evidence_id, hypothesis_id, {"stance": stance.value})

    async def link_same_entity(
        self, entity_a: str, entity_b: str, *, confidence: float = 1.0, method: str = ""
    ) -> str:
        return await self._upsert_edge(
            "SAME_ENTITY", entity_a, entity_b, {"confidence": confidence, "method": method}
        )

    async def link_application_record(self, link: ApplicationLink) -> str:
        """``entity OPENED_AS application record`` for enterprise deep links."""
        await self._upsert_node(
            f"app:{link.entity_type.value}:{link.record_id}",
            "ApplicationRecord",
            {"record_id": link.record_id, "url": link.url, "verified": link.verified_in_database},
        )
        return await self._upsert_edge(
            "OPENED_AS",
            link.entity_id,
            f"app:{link.entity_type.value}:{link.record_id}",
            {"label": link.label, "verified": link.verified_in_database},
        )

    async def add_timeline_order(
        self, events: Sequence[TimelineEvent], *, investigation_id: str | None = None
    ) -> list[str]:
        """Create Event nodes and a PRECEDES chain in chronological order."""
        ordered = sorted(events, key=lambda event: (event.occurred_at, event.event_id))
        for event in ordered:
            await self._upsert_node(
                event.event_id,
                "Event",
                {
                    "label": event.label,
                    "detail": event.detail,
                    "occurred_at": event.occurred_at,
                    "precision": event.precision,
                    "modality": event.modality.value,
                    "investigation_id": investigation_id,
                },
            )
            for evidence_ref in event.evidence_ids:
                await self._upsert_edge("DERIVED_FROM", event.event_id, evidence_ref, {})
            for entity_ref in event.entity_ids:
                await self._upsert_edge("REFERS_TO", event.event_id, entity_ref, {})
        for earlier, later in zip(ordered, ordered[1:], strict=False):
            await self._upsert_edge("PRECEDES", earlier.event_id, later.event_id, {})
        return [event.event_id for event in ordered]

    # -- reads ------------------------------------------------------------
    async def subgraph(
        self,
        node_id: str,
        depth: int = 2,
        *,
        edge_types: Sequence[str] | None = None,
        limit: int = DEFAULT_NEIGHBOUR_LIMIT,
    ) -> GraphView:
        types = [validate_edge_type(t) for t in edge_types] if edge_types else None
        payload = await self._store.neighbours(node_id, depth=depth, edge_types=types, limit=limit)
        view = _view_from_payload(payload)
        if not any(node.node_id == node_id for node in view.nodes):
            centre = await self._store.get_node(node_id)
            if centre:
                view = _merge_views([_view_from_payload({"nodes": [centre]}), view])
        return view

    async def neighbours_of_entity(
        self,
        entity_id: str,
        *,
        depth: int = 1,
        edge_types: Sequence[str] | None = None,
        limit: int = DEFAULT_NEIGHBOUR_LIMIT,
    ) -> GraphView:
        return await self.subgraph(entity_id, depth, edge_types=edge_types, limit=limit)

    async def investigation_view(
        self, investigation_id: str, *, depth: int = 1, limit: int = DEFAULT_NEIGHBOUR_LIMIT
    ) -> GraphView:
        """Everything recorded for one investigation, expanded by ``depth``."""
        anchors: list[dict[str, Any]] = []
        for label in ("Evidence", "Hypothesis", "Claim", "Event"):
            found = await self._store.find_nodes(
                label, {"investigation_id": investigation_id}, limit=limit
            )
            anchors.extend(found or [])
        if not anchors:
            log.debug("graph.investigation_view_empty", investigation_id=investigation_id)
            return GraphView()
        views = [_view_from_payload({"nodes": anchors})]
        truncated = len(anchors) > MAX_INVESTIGATION_ANCHORS
        for node in anchors[:MAX_INVESTIGATION_ANCHORS]:
            node_id = _node_id_of(node)
            if not node_id:
                continue
            views.append(_view_from_payload(await self._store.neighbours(node_id, depth=depth, limit=limit)))
        merged = _merge_views(views)
        return merged.model_copy(update={"truncated": merged.truncated or truncated})

    async def counts(self) -> dict[str, int]:
        return await self._store.counts()

    # -- internals --------------------------------------------------------
    async def _upsert_node(self, node_id: str, label: str, properties: Mapping[str, Any]) -> None:
        validate_label(label)
        if not node_id:
            raise GraphVocabularyError("node_id must not be empty")
        await self._store.upsert_node(node_id, [label], _json_safe(properties))

    async def _upsert_edge(
        self, edge_type: str, start: str, end: str, properties: Mapping[str, Any]
    ) -> str:
        validate_edge_type(edge_type)
        if not start or not end:
            raise GraphVocabularyError(f"{edge_type} needs both endpoints (got {start!r} -> {end!r})")
        try:
            return await self._store.upsert_edge(edge_type, start, end, _json_safe(properties))
        except ValueError as exc:
            # The storage layer keeps its own edge allowlist (it is the Cypher
            # injection boundary).  A type this layer requires but that backend
            # does not accept is a configuration gap, not a reason to abandon an
            # investigation - it is reported loudly and the write is skipped.
            if "not allowed" not in str(exc) and type(exc).__name__ != "EdgeTypeError":
                raise
            log.error(
                "graph.edge_type_rejected_by_backend",
                edge_type=edge_type,
                start=start,
                end=end,
                detail=str(exc),
            )
            return ""


def _json_safe(properties: Mapping[str, Any]) -> dict[str, Any]:
    """Graph backends store primitives and primitive arrays only."""
    safe: dict[str, Any] = {}
    for key, value in properties.items():
        if value is None:
            continue
        if isinstance(value, Enum):
            safe[key] = value.value
        elif isinstance(value, datetime):
            safe[key] = value.isoformat()
        elif isinstance(value, (str, int, float, bool)):
            safe[key] = value
        elif isinstance(value, (list, tuple)) and all(isinstance(v, (str, int, float, bool)) for v in value):
            safe[key] = list(value)
        else:
            safe[key] = json.dumps(value, default=str, sort_keys=True)
    return safe


def _node_id_of(raw: Mapping[str, Any]) -> str:
    for key in ("node_id", "id", "element_id", "identity"):
        value = raw.get(key)
        if value:
            return str(value)
    return ""


def _node_from(raw: Mapping[str, Any]) -> GraphNode | None:
    node_id = _node_id_of(raw)
    if not node_id:
        return None
    labels = raw.get("labels") or ([raw["label"]] if raw.get("label") else [])
    properties = raw.get("properties") or raw.get("props") or {}
    return GraphNode(
        node_id=node_id,
        labels=[str(label) for label in labels],
        properties=dict(properties) if isinstance(properties, Mapping) else {},
    )


def _edge_from(raw: Mapping[str, Any]) -> GraphEdge | None:
    edge_type = raw.get("type") or raw.get("edge_type") or raw.get("rel_type")
    start = _first(raw, ("start", "start_id", "from", "source", "start_node"))
    end = _first(raw, ("end", "end_id", "to", "target", "end_node"))
    if not edge_type or not start or not end:
        return None
    properties = raw.get("properties") or raw.get("props") or {}
    edge_id = str(raw.get("edge_id") or raw.get("id") or f"{start}-{edge_type}->{end}")
    return GraphEdge(
        edge_id=edge_id,
        type=str(edge_type),
        start=str(start),
        end=str(end),
        properties=dict(properties) if isinstance(properties, Mapping) else {},
    )


def _first(raw: Mapping[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = raw.get(key)
        if value:
            return str(value)
    return ""


def _view_from_payload(payload: Mapping[str, Any] | None) -> GraphView:
    """Normalise a backend neighbours() payload into a GraphView."""
    if not payload:
        return GraphView()
    raw_nodes = payload.get("nodes") or []
    raw_edges = payload.get("edges") or payload.get("relationships") or payload.get("rels") or []
    nodes = [node for node in (_node_from(n) for n in raw_nodes if isinstance(n, Mapping)) if node]
    edges = [edge for edge in (_edge_from(e) for e in raw_edges if isinstance(e, Mapping)) if edge]
    skipped = (len(raw_nodes) - len(nodes)) + (len(raw_edges) - len(edges))
    if skipped:
        log.warning("graph.view_entries_skipped", skipped=skipped)
    return GraphView(nodes=nodes, edges=edges, truncated=bool(payload.get("truncated")))


def _merge_views(views: Sequence[GraphView]) -> GraphView:
    nodes: dict[str, GraphNode] = {}
    edges: dict[str, GraphEdge] = {}
    truncated = False
    for view in views:
        for node in view.nodes:
            nodes.setdefault(node.node_id, node)
        for edge in view.edges:
            edges.setdefault(f"{edge.start}-{edge.type}->{edge.end}", edge)
        truncated = truncated or view.truncated
    return GraphView(nodes=list(nodes.values()), edges=list(edges.values()), truncated=truncated)
