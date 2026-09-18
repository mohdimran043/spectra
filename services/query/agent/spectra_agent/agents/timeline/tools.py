"""Timeline Builder tool: order the dated evidence into what happened when."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from spectra_schemas import AgentName, EvidenceItem, Modality, TimelineEvent, ToolResult, ToolSpec

from ...context import ToolContext
from ...evidence_adapter import maybe_await
from ...tools.base import Tool
from ...tools.ledger import select_evidence
from ...tools.payloads import dump
from ...tools.schemas import integer, obj, string_array
from ...tools.timeouts import EVIDENCE_TIMEOUT_SECONDS

DEFAULT_EVENT_LIMIT = 25
MAX_EVENT_LIMIT = 100
# A timeline label is a headline, not the evidence itself.
MAX_LABEL_CHARS = 120


class BuildTimelineTool(Tool):
    spec = ToolSpec(
        name="build_timeline",
        description="Order the dated evidence into a timeline of what happened when.",
        agent=AgentName.TIMELINE,
        input_schema=obj(
            {
                "evidence_ids": string_array("Restrict the timeline to these evidence ids"),
                "limit": integer("Maximum events", default=DEFAULT_EVENT_LIMIT, maximum=MAX_EVENT_LIMIT),
            }
        ),
        output_schema=obj(
            {
                "events": {"type": "array", "description": "TimelineEvent payloads", "items": {"type": "object"}},
                "narrative": {"type": "string", "description": "Plain-language description"},
            }
        ),
        timeout_seconds=EVIDENCE_TIMEOUT_SECONDS,
        cost_hint=0.4,
    )

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        items = select_evidence(ctx, args.get("evidence_ids"), limit=int(args.get("limit", DEFAULT_EVENT_LIMIT)))
        dated = [item for item in items if item.occurred_at is not None]
        if not dated:
            return self.empty("no gathered evidence carries a timestamp")
        builder = getattr(getattr(ctx.services.evidence, "timeline", None), "build", None)
        events = await maybe_await(builder(dated)) if builder is not None else None
        if not events:
            events = _local_timeline(dated)
        narrative = await self._describe(ctx, events)
        return self.success(
            data={"events": dump(events), "narrative": narrative},
            summary=f"{len(events)} timeline event(s)",
            count=len(events),
        )

    async def _describe(self, ctx: ToolContext, events: Sequence[Any]) -> str:
        describe = getattr(getattr(ctx.services.evidence, "timeline", None), "describe", None)
        if describe is None:
            return " → ".join(getattr(e, "label", str(e)) for e in events)
        return str(await maybe_await(describe(list(events))) or "")


def _local_timeline(items: Sequence[EvidenceItem]) -> list[TimelineEvent]:
    ordered = sorted(items, key=lambda i: i.occurred_at)  # type: ignore[arg-type,return-value]
    return [
        TimelineEvent(
            event_id=f"tev_{item.evidence_id[-8:]}",
            occurred_at=item.occurred_at,  # type: ignore[arg-type]
            label=item.summary[:MAX_LABEL_CHARS],
            detail=item.citation(),
            modality=item.modality if isinstance(item.modality, Modality) else Modality.DOCUMENT,
            evidence_ids=[item.evidence_id],
            entity_ids=list(item.entities),
            source_id=item.provenance.source_id,
        )
        for item in ordered
    ]


TIMELINE_TOOLS: tuple[type[Tool], ...] = (BuildTimelineTool,)
