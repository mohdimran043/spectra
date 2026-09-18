"""Reading the investigation's own evidence ledger from inside a tool.

The Brain, the contradiction radar and the timeline builder all re-read evidence
that earlier tool calls already gathered, and they all want the same thing: the
heaviest items, optionally narrowed to a set of ids.
"""

from __future__ import annotations

from collections.abc import Sequence

from spectra_schemas import EvidenceItem

from ..context import ToolContext


def select_evidence(
    ctx: ToolContext, evidence_ids: Sequence[str] | None, limit: int
) -> list[EvidenceItem]:
    """The ``limit`` heaviest ledger items, restricted to ``evidence_ids`` when given."""
    items = list(ctx.ledger().items)
    if evidence_ids:
        wanted = set(evidence_ids)
        items = [item for item in items if item.evidence_id in wanted]
    return sorted(items, key=lambda i: i.weight, reverse=True)[:limit]
