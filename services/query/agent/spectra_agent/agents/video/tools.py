"""Video Agent tools: search video content, and read one second of it."""

from __future__ import annotations

from typing import Any

from spectra_schemas import (
    AgentName,
    EvidenceKind,
    Modality,
    Provenance,
    ToolResult,
    ToolSpec,
    VideoLocator,
)

from ...context import ToolContext
from ...evidence_adapter import maybe_await
from ...tools.assets import asset_for, evidence_for_chunk, locator_value, repository_for
from ...tools.base import Tool
from ...tools.modality_search import ModalitySearchTool
from ...tools.payloads import evidence_payload
from ...tools.schemas import EVIDENCE_OUTPUT, SEARCH_INPUT, obj, string
from ...tools.timeouts import LOCATOR_TIMEOUT_SECONDS, SEARCH_MEDIA_TIMEOUT_SECONDS

# A claim pinned to a video second is checked by watching a few seconds either
# side of it, so the default window is symmetric and small.
DEFAULT_WINDOW_SECONDS = 5.0
MAX_WINDOW_SECONDS = 120.0


class SearchVideosTool(ModalitySearchTool):
    modality = Modality.VIDEO
    spec = ToolSpec(
        name="search_videos",
        description=(
            "Search video scenes, frames and spoken content. Evidence carries the "
            "video id and the second offset the claim came from."
        ),
        agent=AgentName.VIDEO,
        input_schema=SEARCH_INPUT,
        output_schema=EVIDENCE_OUTPUT,
        timeout_seconds=SEARCH_MEDIA_TIMEOUT_SECONDS,
        gpu_heavy=True,
        requires_flag="video",
        cost_hint=2.5,
    )


class GetVideoTimestampTool(Tool):
    spec = ToolSpec(
        name="get_video_timestamp",
        description="Read what a video shows or says around a given second.",
        agent=AgentName.VIDEO,
        input_schema=obj(
            {
                "video_id": string("Asset id of the video"),
                "seconds": {"type": "number", "description": "Offset in seconds", "minimum": 0},
                "window_seconds": {
                    "type": "number",
                    "description": "Half-window around the offset",
                    "default": DEFAULT_WINDOW_SECONDS,
                    "minimum": 0,
                    "maximum": MAX_WINDOW_SECONDS,
                },
            },
            required=["video_id", "seconds"],
        ),
        output_schema=EVIDENCE_OUTPUT,
        timeout_seconds=LOCATOR_TIMEOUT_SECONDS,
        requires_flag="video",
        cost_hint=0.4,
    )

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        asset = await asset_for(ctx, self.spec.name, args["video_id"])
        repository = await repository_for(ctx, self.spec.name)
        target = float(args["seconds"])
        window = float(args.get("window_seconds", DEFAULT_WINDOW_SECONDS))
        chunks = list(await maybe_await(repository.list_chunks_by_asset(asset.asset_id)) or [])
        matches = [c for c in chunks if _overlaps(c, target, window)]
        if not matches:
            return self.empty(f"nothing indexed for {asset.title} at {target:.1f}s (±{window:.1f}s)")
        items = [
            evidence_for_chunk(
                chunk,
                asset,
                Provenance(
                    source_id=chunk.source_id,
                    modality=Modality.VIDEO,
                    object_uri=asset.object_uri,
                    locator=VideoLocator(
                        video_id=asset.asset_id,
                        start_seconds=float(locator_value(chunk, "start_seconds") or target),
                        end_seconds=float(locator_value(chunk, "end_seconds") or target + window),
                    ),
                ),
                EvidenceKind.VIDEO,
                self.spec.name,
            )
            for chunk in matches
        ]
        return self.success(
            data=evidence_payload(items),
            summary=f"{len(items)} segment(s) of '{asset.title}' around {target:.1f}s",
            count=len(items),
            evidence_ids=[item.evidence_id for item in items],
        )


def _overlaps(chunk: Any, target: float, window: float) -> bool:
    start = locator_value(chunk, "start_seconds")
    end = locator_value(chunk, "end_seconds")
    if start is None and end is None:
        return False
    low = float(start if start is not None else 0.0)
    high = float(end if end is not None else low)
    return low - window <= target <= high + window


VIDEO_TOOLS: tuple[type[Tool], ...] = (SearchVideosTool, GetVideoTimestampTool)
