"""Neo4j graph store (distributed profile).

Cypher can parameterise values but *not* labels or relationship types, so those
are the two places where caller input would otherwise be concatenated into a
query.  Both are validated against ``graph_schema`` before interpolation, and
every other value travels as a bound parameter.  Nested property values are kept
verbatim in a JSON side-property because Neo4j only stores primitives.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from spectra_config import Settings
from spectra_config.logging import get_logger

from ..graph_schema import deterministic_edge_id, validate_edge_type, validate_label
from ..interfaces import GraphStore

log = get_logger(__name__)

BASE_LABEL = "SpectraNode"
PROPERTIES_KEY = "properties_json"
NODE_KIND = "node"
EDGE_KIND = "edge"
DEFAULT_NEIGHBOUR_LIMIT = 100
MAX_PATHS = 25
MAX_PATH_DEPTH = 8
CONNECTION_TIMEOUT_SECONDS = 10
_PRIMITIVES = (str, int, float, bool)


class Neo4jGraphStore(GraphStore):
    """Property graph backed by an async Neo4j driver."""

    backend_name = "neo4j"

    def __init__(self, settings: Settings) -> None:
        from neo4j import AsyncGraphDatabase  # lazy: optional dependency

        self._settings = settings
        self._driver = AsyncGraphDatabase.driver(
            settings.neo4j_url,
            auth=(settings.neo4j_user, settings.neo4j_password),
            connection_timeout=CONNECTION_TIMEOUT_SECONDS,
        )

    # -- lifecycle --------------------------------------------------------
    async def probe(self) -> None:
        """Raise unless the database answers - used by the factory at start-up."""
        await self._driver.verify_connectivity()

    async def close(self) -> None:
        await self._driver.close()

    async def _query(self, cypher: str, **params: Any) -> list[dict[str, Any]]:
        async with self._driver.session() as session:
            result = await session.run(cypher, **params)
            return [record.data() async for record in result]

    async def _query_records(self, cypher: str, **params: Any) -> list[Any]:
        async with self._driver.session() as session:
            result = await session.run(cypher, **params)
            return [record async for record in result]

    # -- writes -----------------------------------------------------------
    async def upsert_node(self, node_id: str, labels: Sequence[str], properties: dict[str, Any]) -> None:
        if not node_id:
            raise ValueError("node_id must not be empty")
        safe_labels = [validate_label(label) for label in labels or []]
        label_clause = "".join(f":{label}" for label in safe_labels)
        cypher = (
            f"MERGE (n:{BASE_LABEL} {{node_id: $node_id}}) "
            f"SET n += $flat, n.{PROPERTIES_KEY} = $properties_json"
        )
        if label_clause:
            cypher = f"{cypher} SET n{label_clause}"
        await self._query(
            cypher,
            node_id=node_id,
            flat=_flatten(properties or {}),
            properties_json=json.dumps(properties or {}, default=str),
        )

    async def upsert_edge(
        self,
        edge_type: str,
        start: str,
        end: str,
        properties: dict[str, Any] | None = None,
    ) -> str:
        canonical = validate_edge_type(edge_type)
        if not start or not end:
            raise ValueError("edge endpoints must both be non-empty node ids")
        edge_id = deterministic_edge_id(canonical, start, end)
        cypher = (
            f"MERGE (a:{BASE_LABEL} {{node_id: $start}}) "
            f"MERGE (b:{BASE_LABEL} {{node_id: $end}}) "
            f"MERGE (a)-[r:{canonical}]->(b) "
            f"SET r += $flat, r.edge_id = $edge_id, r.{PROPERTIES_KEY} = $properties_json "
            "RETURN r.edge_id AS edge_id"
        )
        rows = await self._query(
            cypher,
            start=start,
            end=end,
            edge_id=edge_id,
            flat=_flatten(properties or {}),
            properties_json=json.dumps(properties or {}, default=str),
        )
        return str(rows[0]["edge_id"]) if rows else edge_id

    # -- reads ------------------------------------------------------------
    async def get_node(self, node_id: str) -> dict[str, Any] | None:
        records = await self._query_records(
            f"MATCH (n:{BASE_LABEL} {{node_id: $node_id}}) RETURN n LIMIT 1", node_id=node_id
        )
        if not records:
            return None
        return _node_dict(records[0]["n"])

    async def find_nodes(
        self, label: str, properties: dict[str, Any] | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        safe_label = validate_label(label)
        wanted = _flatten(properties or {})
        records = await self._query_records(
            f"MATCH (n:{safe_label}) WHERE all(k IN keys($props) WHERE n[k] = $props[k]) "
            "RETURN n ORDER BY n.node_id LIMIT $limit",
            props=wanted,
            limit=max(int(limit), 0),
        )
        return [_node_dict(record["n"]) for record in records]

    async def neighbours(
        self,
        node_id: str,
        depth: int = 1,
        edge_types: Sequence[str] | None = None,
        limit: int = DEFAULT_NEIGHBOUR_LIMIT,
    ) -> dict[str, Any]:
        types = [validate_edge_type(t) for t in edge_types or []]
        bounded_depth = max(min(int(depth), MAX_PATH_DEPTH), 0)
        root = await self.get_node(node_id)
        if root is None:
            return {"root": node_id, "depth": bounded_depth, "nodes": [], "edges": [], "truncated": False}
        if bounded_depth == 0:
            return {"root": node_id, "depth": 0, "nodes": [root], "edges": [], "truncated": False}
        records = await self._query_records(
            f"MATCH p = (root:{BASE_LABEL} {{node_id: $node_id}})-[rels*1..{bounded_depth}]-(other) "
            "WHERE size($types) = 0 OR all(r IN rels WHERE type(r) IN $types) "
            "RETURN nodes(p) AS ns, relationships(p) AS rs LIMIT $limit",
            node_id=node_id,
            types=types,
            limit=max(int(limit), 0),
        )
        return _collect_paths(node_id, bounded_depth, root, records, max(int(limit), 0))

    async def paths(self, start: str, end: str, max_depth: int = 4) -> list[list[dict[str, Any]]]:
        bounded = max(min(int(max_depth), MAX_PATH_DEPTH), 1)
        records = await self._query_records(
            f"MATCH p = (a:{BASE_LABEL} {{node_id: $start}})-[*1..{bounded}]-(b:{BASE_LABEL} "
            "{node_id: $end}) RETURN nodes(p) AS ns, relationships(p) AS rs LIMIT $max_paths",
            start=start,
            end=end,
            max_paths=MAX_PATHS,
        )
        return [_interleave(record["ns"], record["rs"]) for record in records]

    async def counts(self) -> dict[str, int]:
        totals: dict[str, int] = {}
        node_rows = await self._query(f"MATCH (n:{BASE_LABEL}) RETURN count(n) AS total")
        edge_rows = await self._query("MATCH ()-[r]->() RETURN count(r) AS total")
        totals["nodes"] = int(node_rows[0]["total"]) if node_rows else 0
        totals["edges"] = int(edge_rows[0]["total"]) if edge_rows else 0
        for row in await self._query(
            f"MATCH (n:{BASE_LABEL}) UNWIND labels(n) AS label "
            "RETURN label, count(*) AS total ORDER BY label"
        ):
            if row["label"] != BASE_LABEL:
                totals[f"label:{row['label']}"] = int(row["total"])
        for row in await self._query(
            "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS total ORDER BY type"
        ):
            totals[f"edge:{row['type']}"] = int(row["total"])
        return totals

    async def health(self) -> dict[str, Any]:
        try:
            await self._driver.verify_connectivity()
            totals = await self.counts()
        except Exception as exc:  # health must never raise
            log.warning("graph.health_failed", backend=self.backend_name, error=str(exc))
            return {"backend": self.backend_name, "status": "error", "detail": str(exc)}
        return {
            "backend": self.backend_name,
            "status": "ok",
            "url": self._settings.neo4j_url,
            "nodes": totals["nodes"],
            "edges": totals["edges"],
        }


# -- mapping --------------------------------------------------------------
def _flatten(properties: dict[str, Any]) -> dict[str, Any]:
    """Only primitives (and primitive lists) may be stored as Neo4j properties."""
    flat: dict[str, Any] = {}
    for key, value in properties.items():
        if isinstance(value, _PRIMITIVES) or value is None:
            flat[key] = value
        elif isinstance(value, (list, tuple)) and all(isinstance(v, _PRIMITIVES) for v in value):
            flat[key] = list(value)
    return flat


def _node_dict(node: Any) -> dict[str, Any]:
    raw = dict(node)
    encoded = raw.pop(PROPERTIES_KEY, None)
    properties = json.loads(encoded) if encoded else {k: v for k, v in raw.items() if k != "node_id"}
    return {
        "kind": NODE_KIND,
        "node_id": raw.get("node_id", ""),
        "labels": [label for label in getattr(node, "labels", []) if label != BASE_LABEL],
        "properties": properties,
    }


def _edge_dict(relationship: Any) -> dict[str, Any]:
    raw = dict(relationship)
    encoded = raw.pop(PROPERTIES_KEY, None)
    edge_id = raw.pop("edge_id", "")
    properties = json.loads(encoded) if encoded else raw
    return {
        "kind": EDGE_KIND,
        "edge_id": str(edge_id),
        "type": getattr(relationship, "type", ""),
        "start": _endpoint(relationship, "start_node"),
        "end": _endpoint(relationship, "end_node"),
        "properties": properties,
    }


def _endpoint(relationship: Any, attribute: str) -> str:
    node = getattr(relationship, attribute, None)
    if node is None:
        return ""
    return str(dict(node).get("node_id", ""))


def _interleave(nodes: Sequence[Any], relationships: Sequence[Any]) -> list[dict[str, Any]]:
    path: list[dict[str, Any]] = [_node_dict(nodes[0])] if nodes else []
    for relationship, node in zip(relationships, nodes[1:], strict=False):
        path.append(_edge_dict(relationship))
        path.append(_node_dict(node))
    return path


def _collect_paths(
    root_id: str, depth: int, root: dict[str, Any], records: Sequence[Any], limit: int
) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {root_id: root}
    edges: dict[str, dict[str, Any]] = {}
    truncated = False
    for record in records:
        for relationship in record["rs"]:
            edge = _edge_dict(relationship)
            edges[edge["edge_id"] or f"{edge['start']}->{edge['end']}"] = edge
        for node in record["ns"]:
            mapped = _node_dict(node)
            if mapped["node_id"] in nodes:
                continue
            if len(nodes) >= limit:
                truncated = True
                continue
            nodes[mapped["node_id"]] = mapped
    return {
        "root": root_id,
        "depth": depth,
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
        "truncated": truncated,
    }
