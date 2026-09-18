"""Serialisation helpers between tools and the Brain.

``ToolResult.data`` stays JSON-safe so it can be logged, traced and streamed, so
evidence crosses that boundary as plain dictionaries and is re-validated on the
Brain side.  ``dump`` does the same for the payloads peer services hand back.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from pydantic import BaseModel
from spectra_config.logging import get_logger
from spectra_schemas import EvidenceItem, ToolResult

log = get_logger(__name__)


def pack_evidence(items: Iterable[EvidenceItem]) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in items]


def unpack_evidence(result: ToolResult) -> list[EvidenceItem]:
    """Rebuild evidence from a tool result, skipping anything malformed."""
    raw = result.data.get("evidence") if result.data else None
    if not isinstance(raw, list):
        return []
    items: list[EvidenceItem] = []
    for payload in raw:
        if isinstance(payload, EvidenceItem):
            items.append(payload)
            continue
        try:
            items.append(EvidenceItem.model_validate(payload))
        except Exception as exc:  # pragma: no cover - defensive, malformed peer payload
            log.warning("tool.evidence_discarded", tool=result.tool, error=str(exc))
    return items


def evidence_payload(items: Sequence[EvidenceItem]) -> dict[str, Any]:
    return {
        "evidence": pack_evidence(items),
        "count": len(items),
        "sources": sorted({item.provenance.source_id for item in items}),
    }


def dump(value: Any) -> Any:
    """JSON-safe rendering of a peer service payload."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, (list, tuple)):
        return [dump(item) for item in value]
    if isinstance(value, dict):
        return {key: dump(item) for key, item in value.items()}
    return value
