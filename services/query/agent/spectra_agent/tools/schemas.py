"""Reusable JSON-schema fragments for tool declarations.

Declaring these once keeps the 22 tool specs consistent and keeps each tool
module focused on behaviour rather than boilerplate.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

MAX_TOP_K = 50
DEFAULT_TOP_K = 10
# Chasing one claim fans out across every enabled modality, so its per-modality
# budget is smaller than a plain search's.
DEFAULT_CLAIM_TOP_K = 6


def obj(properties: dict[str, Any], required: Sequence[str] = ()) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def string(description: str, *, default: str | None = None, enum: Sequence[str] | None = None) -> dict[str, Any]:
    spec: dict[str, Any] = {"type": "string", "description": description, "minLength": 1}
    if default is not None:
        spec["default"] = default
    if enum is not None:
        spec["enum"] = list(enum)
    return spec


def integer(description: str, *, default: int, minimum: int = 1, maximum: int = 100) -> dict[str, Any]:
    return {
        "type": "integer",
        "description": description,
        "default": default,
        "minimum": minimum,
        "maximum": maximum,
    }


def string_array(description: str, *, max_items: int = 25) -> dict[str, Any]:
    return {
        "type": "array",
        "description": description,
        "items": {"type": "string"},
        "maxItems": max_items,
    }


QUERY = string("Natural-language query to retrieve against")
TOP_K = integer("Maximum hits to return", default=DEFAULT_TOP_K, minimum=1, maximum=MAX_TOP_K)
SOURCE_IDS = string_array("Restrict retrieval to these source ids")

SEARCH_INPUT = obj({"query": QUERY, "top_k": TOP_K, "source_ids": SOURCE_IDS}, required=["query"])

EVIDENCE_OUTPUT = obj(
    {
        "evidence": {"type": "array", "description": "EvidenceItem payloads", "items": {"type": "object"}},
        "count": {"type": "integer", "description": "Number of evidence items returned"},
        "sources": string_array("Distinct source ids represented"),
    }
)

RECORDS_OUTPUT = obj(
    {
        "records": {"type": "array", "description": "Matching records", "items": {"type": "object"}},
        "count": {"type": "integer", "description": "Number of records returned"},
    }
)

TEXT_OUTPUT = obj({"text": {"type": "string", "description": "Rendered result"}})
