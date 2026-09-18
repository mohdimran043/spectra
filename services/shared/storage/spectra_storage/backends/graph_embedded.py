"""Embedded property graph: nodes, edges and traversals over SQLite.

Entity/evidence graphs are how SPECTRA connects a transaction to a CCTV frame to
an incident ticket, so graph traversal has to work with zero infrastructure.
Labels are denormalised into their own indexed table because a JSON array cannot
be indexed portably, and traversals are plain BFS/DFS with hard bounds - an
unbounded graph walk is the classic way to hang an investigation.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from typing import Any

from spectra_config import Settings
from spectra_config.logging import get_logger

from ..graph_schema import deterministic_edge_id, validate_edge_type
from ..interfaces import GraphStore
from ..sqlite_support import SqliteDatabase, fetch_all, fetch_one, scalar

log = get_logger(__name__)

GRAPH_DB_FILENAME = "graph.db"
DEFAULT_NEIGHBOUR_LIMIT = 100
MAX_PATHS = 25
MAX_PATH_DEPTH = 8
MAX_LABEL_SCAN = 10_000
NODE_KIND = "node"
EDGE_KIND = "edge"


class EmbeddedGraphStore(GraphStore):
    """SQLite-backed property graph with bounded traversals."""

    backend_name = "embedded"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._db = SqliteDatabase(settings.runtime_dir / GRAPH_DB_FILENAME)
        self._ready = False

    # -- lifecycle --------------------------------------------------------
    async def _ensure_schema(self) -> None:
        if self._ready:
            return
        await self._db.run(_create_schema)
        self._ready = True

    async def close(self) -> None:
        await self._db.close()

    # -- writes -----------------------------------------------------------
    async def upsert_node(self, node_id: str, labels: Sequence[str], properties: dict[str, Any]) -> None:
        if not node_id:
            raise ValueError("node_id must not be empty")
        await self._ensure_schema()
        clean_labels = [str(label) for label in labels or []]
        payload = json.dumps(properties or {}, default=str)

        def _write(connection: sqlite3.Connection) -> None:
            connection.execute(
                "INSERT INTO nodes(node_id, labels, properties) VALUES(?, ?, ?) "
                "ON CONFLICT(node_id) DO UPDATE SET labels = excluded.labels, properties = excluded.properties",
                (node_id, json.dumps(clean_labels), payload),
            )
            connection.execute("DELETE FROM node_labels WHERE node_id = ?", (node_id,))
            connection.executemany(
                "INSERT INTO node_labels(node_id, label) VALUES(?, ?) ON CONFLICT DO NOTHING",
                [(node_id, label) for label in clean_labels],
            )

        await self._db.run(_write)

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
        await self._ensure_schema()
        edge_id = deterministic_edge_id(canonical, start, end)
        payload = json.dumps(properties or {}, default=str)

        def _write(connection: sqlite3.Connection) -> None:
            for node_id in (start, end):
                connection.execute(
                    "INSERT INTO nodes(node_id, labels, properties) VALUES(?, '[]', '{}') "
                    "ON CONFLICT(node_id) DO NOTHING",
                    (node_id,),
                )
            connection.execute(
                "INSERT INTO edges(edge_id, type, start_id, end_id, properties) VALUES(?, ?, ?, ?, ?) "
                "ON CONFLICT(edge_id) DO UPDATE SET properties = excluded.properties",
                (edge_id, canonical, start, end, payload),
            )

        await self._db.run(_write)
        return edge_id

    # -- reads ------------------------------------------------------------
    async def get_node(self, node_id: str) -> dict[str, Any] | None:
        await self._ensure_schema()

        def _read(connection: sqlite3.Connection) -> sqlite3.Row | None:
            return fetch_one(
                connection, "SELECT node_id, labels, properties FROM nodes WHERE node_id = ?", (node_id,)
            )

        row = await self._db.run(_read)
        return _node_dict(row) if row is not None else None

    async def find_nodes(
        self, label: str, properties: dict[str, Any] | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        await self._ensure_schema()
        wanted = dict(properties or {})

        def _read(connection: sqlite3.Connection) -> list[sqlite3.Row]:
            if not wanted:
                return fetch_all(
                    connection,
                    "SELECT n.node_id, n.labels, n.properties FROM nodes n "
                    "JOIN node_labels l ON l.node_id = n.node_id WHERE l.label = ? "
                    "ORDER BY n.node_id LIMIT ?",
                    (label, max(limit, 0)),
                )
            return fetch_all(
                connection,
                "SELECT n.node_id, n.labels, n.properties FROM nodes n "
                "JOIN node_labels l ON l.node_id = n.node_id WHERE l.label = ? "
                "ORDER BY n.node_id LIMIT ?",
                (label, MAX_LABEL_SCAN),
            )

        rows = await self._db.run(_read)
        if wanted and len(rows) >= MAX_LABEL_SCAN:
            log.warning("graph.label_scan_capped", label=label, scanned=len(rows), cap=MAX_LABEL_SCAN)
        matched = [_node_dict(row) for row in rows]
        if not wanted:
            return matched
        return [node for node in matched if _properties_match(node["properties"], wanted)][: max(limit, 0)]

    async def neighbours(
        self,
        node_id: str,
        depth: int = 1,
        edge_types: Sequence[str] | None = None,
        limit: int = DEFAULT_NEIGHBOUR_LIMIT,
    ) -> dict[str, Any]:
        await self._ensure_schema()
        types = [validate_edge_type(t) for t in edge_types or []]
        bounded_depth = max(min(int(depth), MAX_PATH_DEPTH), 0)

        def _walk(connection: sqlite3.Connection) -> dict[str, Any]:
            return _breadth_first(connection, node_id, bounded_depth, types, max(limit, 0))

        result = await self._db.run(_walk)
        log.debug(
            "graph.neighbours",
            backend=self.backend_name,
            node_id=node_id,
            depth=bounded_depth,
            nodes=len(result["nodes"]),
            edges=len(result["edges"]),
        )
        return result

    async def paths(self, start: str, end: str, max_depth: int = 4) -> list[list[dict[str, Any]]]:
        await self._ensure_schema()
        bounded = max(min(int(max_depth), MAX_PATH_DEPTH), 1)

        def _search(connection: sqlite3.Connection) -> list[list[dict[str, Any]]]:
            origin = fetch_one(
                connection, "SELECT node_id, labels, properties FROM nodes WHERE node_id = ?", (start,)
            )
            if origin is None:
                return []
            found: list[list[dict[str, Any]]] = []
            _depth_first(connection, start, end, bounded, [_node_dict(origin)], {start}, found)
            return found

        return await self._db.run(_search)

    async def counts(self) -> dict[str, int]:
        await self._ensure_schema()

        def _read(connection: sqlite3.Connection) -> dict[str, int]:
            totals: dict[str, int] = {
                "nodes": scalar(connection, "SELECT COUNT(*) FROM nodes"),
                "edges": scalar(connection, "SELECT COUNT(*) FROM edges"),
            }
            for row in fetch_all(
                connection, "SELECT label, COUNT(*) AS total FROM node_labels GROUP BY label ORDER BY label"
            ):
                totals[f"label:{row['label']}"] = int(row["total"])
            for row in fetch_all(
                connection, "SELECT type, COUNT(*) AS total FROM edges GROUP BY type ORDER BY type"
            ):
                totals[f"edge:{row['type']}"] = int(row["total"])
            return totals

        return await self._db.run(_read)

    async def health(self) -> dict[str, Any]:
        try:
            totals = await self.counts()
        except sqlite3.Error as exc:
            log.warning("graph.health_failed", backend=self.backend_name, error=str(exc))
            return {"backend": self.backend_name, "status": "error", "detail": str(exc)}
        return {
            "backend": self.backend_name,
            "status": "ok",
            "path": str(self._db.path),
            "nodes": totals["nodes"],
            "edges": totals["edges"],
        }


# -- schema ---------------------------------------------------------------
def _create_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS nodes (node_id TEXT PRIMARY KEY, labels TEXT NOT NULL DEFAULT '[]', "
        "properties TEXT NOT NULL DEFAULT '{}')"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS node_labels (node_id TEXT NOT NULL, label TEXT NOT NULL, "
        "PRIMARY KEY(node_id, label))"
    )
    connection.execute("CREATE INDEX IF NOT EXISTS node_labels_label ON node_labels(label)")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS edges (edge_id TEXT PRIMARY KEY, type TEXT NOT NULL, "
        "start_id TEXT NOT NULL, end_id TEXT NOT NULL, properties TEXT NOT NULL DEFAULT '{}')"
    )
    connection.execute("CREATE INDEX IF NOT EXISTS edges_start ON edges(start_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS edges_end ON edges(end_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS edges_type ON edges(type)")


# -- traversal ------------------------------------------------------------
def _breadth_first(
    connection: sqlite3.Connection,
    root: str,
    depth: int,
    types: Sequence[str],
    limit: int,
) -> dict[str, Any]:
    seen: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    origin = fetch_one(connection, "SELECT node_id, labels, properties FROM nodes WHERE node_id = ?", (root,))
    if origin is None:
        return {"root": root, "depth": depth, "nodes": [], "edges": [], "truncated": False}
    seen[root] = _node_dict(origin)
    frontier = [root]
    truncated = False
    for _level in range(depth):
        if not frontier or len(seen) >= limit:
            truncated = truncated or bool(frontier)
            break
        rows = _incident_edges(connection, frontier, types)
        frontier = []
        for row in rows:
            edges[row["edge_id"]] = _edge_dict(row)
            for candidate in (row["start_id"], row["end_id"]):
                if candidate in seen:
                    continue
                if len(seen) >= limit:
                    truncated = True
                    continue
                node = fetch_one(
                    connection,
                    "SELECT node_id, labels, properties FROM nodes WHERE node_id = ?",
                    (candidate,),
                )
                if node is not None:
                    seen[candidate] = _node_dict(node)
                    frontier.append(candidate)
    return {
        "root": root,
        "depth": depth,
        "nodes": list(seen.values()),
        "edges": list(edges.values()),
        "truncated": truncated,
    }


def _incident_edges(
    connection: sqlite3.Connection, frontier: Sequence[str], types: Sequence[str]
) -> list[sqlite3.Row]:
    node_slots = ",".join("?" for _ in frontier)
    sql = (
        "SELECT edge_id, type, start_id, end_id, properties FROM edges "
        f"WHERE (start_id IN ({node_slots}) OR end_id IN ({node_slots}))"
    )
    params: list[Any] = [*frontier, *frontier]
    if types:
        sql += f" AND type IN ({','.join('?' for _ in types)})"
        params.extend(types)
    return fetch_all(connection, f"{sql} ORDER BY edge_id", tuple(params))


def _depth_first(
    connection: sqlite3.Connection,
    current: str,
    target: str,
    budget: int,
    trail: list[dict[str, Any]],
    visited: set[str],
    found: list[list[dict[str, Any]]],
) -> None:
    if len(found) >= MAX_PATHS:
        return
    if current == target and len(trail) > 1:
        found.append(list(trail))
        return
    if budget <= 0:
        return
    for row in _incident_edges(connection, [current], []):
        nxt = row["end_id"] if row["start_id"] == current else row["start_id"]
        if nxt in visited:
            continue
        node = fetch_one(connection, "SELECT node_id, labels, properties FROM nodes WHERE node_id = ?", (nxt,))
        if node is None:
            continue
        _depth_first(
            connection,
            nxt,
            target,
            budget - 1,
            [*trail, _edge_dict(row), _node_dict(node)],
            visited | {nxt},
            found,
        )


# -- row mapping ----------------------------------------------------------
def _node_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "kind": NODE_KIND,
        "node_id": row["node_id"],
        "labels": json.loads(row["labels"]),
        "properties": json.loads(row["properties"]),
    }


def _edge_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "kind": EDGE_KIND,
        "edge_id": row["edge_id"],
        "type": row["type"],
        "start": row["start_id"],
        "end": row["end_id"],
        "properties": json.loads(row["properties"]),
    }


def _properties_match(properties: dict[str, Any], wanted: dict[str, Any]) -> bool:
    return all(properties.get(key) == value for key, value in wanted.items())
