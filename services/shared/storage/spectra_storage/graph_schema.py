"""Shared graph vocabulary for the embedded and Neo4j graph backends.

Cypher cannot parameterise a relationship type, so an edge type always ends up
interpolated into the query string.  Every edge type is therefore checked
against this allowlist *before* it reaches either backend: it is the injection
boundary for the graph layer, and applying it to both backends keeps a
laptop install and a cluster install accepting exactly the same graph.
"""

from __future__ import annotations

import hashlib
import re

NODE_LABEL_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
EDGE_ID_LENGTH = 20

# The twelve relationship types the evidence graph is specified around
# (spectra_evidence.graph.EDGE_TYPES) are canonical and MUST all appear below -
# omitting one silently breaks entity merging or application linking at write
# time.  The remaining entries are the wider vocabulary other writers may use.
EVIDENCE_EDGE_TYPES: frozenset[str] = frozenset(
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

GRAPH_EDGE_TYPES: frozenset[str] = EVIDENCE_EDGE_TYPES | frozenset(
    {
        "RELATED_TO",
        "SAME_AS",
        "ALIAS_OF",
        "PART_OF",
        "BELONGS_TO",
        "OWNS",
        "ASSIGNED_TO",
        "INVOLVES",
        "APPEARS_IN",
        "DERIVED_FROM",
        "EXTRACTED_FROM",
        "EVIDENCE_FOR",
        "SUPPORTS",
        "CONTRADICTS",
        "VERIFIES",
        "TRANSACTED_WITH",
        "TRANSFERRED_TO",
        "LOCATED_AT",
        "OCCURRED_AT",
        "PRECEDES",
        "FOLLOWS",
        "CAUSED_BY",
        "TRIGGERED",
        "REPORTED_BY",
        "LINKED_TO",
        "INVESTIGATES",
        "HAS_HYPOTHESIS",
        "HAS_CHUNK",
        "HAS_ASSET",
        "HAS_ENTITY",
    }
)


class EdgeTypeError(ValueError):
    """Raised when an edge type is not part of the allowlist."""


def validate_edge_type(edge_type: str) -> str:
    """Return the canonical edge type or raise - never interpolate unchecked input."""
    candidate = (edge_type or "").strip().upper()
    if candidate not in GRAPH_EDGE_TYPES:
        raise EdgeTypeError(
            f"edge type {edge_type!r} is not allowed; permitted types: {sorted(GRAPH_EDGE_TYPES)}"
        )
    return candidate


def validate_label(label: str) -> str:
    """Node labels are interpolated into Cypher too, so they are shape-checked."""
    candidate = (label or "").strip()
    if not NODE_LABEL_PATTERN.match(candidate):
        raise ValueError(f"invalid node label {label!r}: expected ^[A-Za-z][A-Za-z0-9_]{{0,63}}$")
    return candidate


def deterministic_edge_id(edge_type: str, start: str, end: str) -> str:
    """Stable id for a (type, start, end) triple so re-ingestion never duplicates edges."""
    digest = hashlib.sha256("\x1f".join((edge_type, start, end)).encode("utf-8")).hexdigest()
    return f"edg_{digest[:EDGE_ID_LENGTH]}"
