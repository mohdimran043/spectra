"""Vision Agent tools: search images, and open one stored image."""

from __future__ import annotations

from typing import Any

from spectra_schemas import (
    AgentName,
    EvidenceItem,
    EvidenceKind,
    ImageLocator,
    Modality,
    Provenance,
    ToolResult,
    ToolSpec,
    evidence_id,
)

from ...context import ToolContext
from ...evidence_adapter import maybe_await, summarise
from ...tools.assets import (
    DEFAULT_SOURCE_RELIABILITY,
    LOCATOR_RELEVANCE,
    asset_for,
)
from ...tools.base import Tool, require_service
from ...tools.modality_search import ModalitySearchTool
from ...tools.payloads import evidence_payload
from ...tools.schemas import EVIDENCE_OUTPUT, QUERY, SOURCE_IDS, TOP_K, obj, string
from ...tools.timeouts import LOCATOR_TIMEOUT_SECONDS, SEARCH_MEDIA_TIMEOUT_SECONDS


class SearchImagesTool(ModalitySearchTool):
    modality = Modality.IMAGE
    spec = ToolSpec(
        name="search_images",
        description=(
            "Search images by description, embedded OCR text or a reference image id. "
            "Returns evidence pointing at the image (and region when known)."
        ),
        agent=AgentName.IMAGE,
        input_schema=obj(
            {
                "query": QUERY,
                "top_k": TOP_K,
                "source_ids": SOURCE_IDS,
                "image_asset_id": string("Reference image asset id for image-to-image search"),
            },
            required=["query"],
        ),
        output_schema=EVIDENCE_OUTPUT,
        timeout_seconds=SEARCH_MEDIA_TIMEOUT_SECONDS,
        gpu_heavy=True,
        requires_flag="image",
        cost_hint=2.0,
    )


class GetImageTool(Tool):
    spec = ToolSpec(
        name="get_image",
        description="Locate a stored image and return its metadata and canonical object URI.",
        agent=AgentName.IMAGE,
        input_schema=obj({"image_id": string("Asset id of the image")}, required=["image_id"]),
        output_schema=obj(
            {
                "image": {"type": "object", "description": "Asset metadata"},
                "object_uri": {"type": "string", "description": "Canonical storage URI"},
                "available": {"type": "boolean", "description": "Whether the bytes are present"},
            }
        ),
        timeout_seconds=LOCATOR_TIMEOUT_SECONDS,
        requires_flag="image",
        cost_hint=0.3,
    )

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        asset = await asset_for(ctx, self.spec.name, args["image_id"])
        storage = require_service(ctx, "storage", self.spec.name)
        objects = getattr(storage, "objects", None)
        available = True
        if objects is not None and hasattr(objects, "exists"):
            available = bool(await maybe_await(objects.exists(asset.object_uri)))
        payload = asset.model_dump(mode="json")
        item = EvidenceItem(
            evidence_id=evidence_id(asset.asset_id, self.spec.name),
            kind=EvidenceKind.IMAGE,
            modality=Modality.IMAGE,
            summary=summarise(asset.title),
            provenance=Provenance(
                source_id=asset.source_id,
                modality=Modality.IMAGE,
                object_uri=asset.object_uri,
                locator=ImageLocator(image_id=asset.asset_id),
            ),
            relevance=LOCATOR_RELEVANCE,
            reliability=DEFAULT_SOURCE_RELIABILITY,
            reliability_reason="image opened directly by asset id",
            retrieved_by=self.spec.name,
        )
        data = evidence_payload([item])
        data |= {"image": payload, "object_uri": asset.object_uri, "available": available}
        return self.success(
            data=data,
            summary=f"image '{asset.title}' ({asset.media_type}){'' if available else ' - bytes missing'}",
            count=1,
            evidence_ids=[item.evidence_id],
            degraded=not available,
            degraded_reason=None if available else "image bytes are not present in the object store",
        )


VISION_TOOLS: tuple[type[Tool], ...] = (SearchImagesTool, GetImageTool)
