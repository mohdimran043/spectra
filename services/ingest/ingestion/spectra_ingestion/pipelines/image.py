"""Image pipeline: metadata + EXIF -> OCR -> caption -> multimodal + text index.

The image gets a vector in ``IMAGE_COLLECTION`` *and* a text chunk holding the
caption and the OCR text, so the same picture is reachable by an image query,
by a semantic text query and by a literal BM25 keyword.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

from PIL import ExifTags, Image, UnidentifiedImageError
from spectra_config.logging import get_logger
from spectra_schemas import Asset, ImageLocator, Modality

from .base import STAGE_EXTRACT, BasePipeline, IngestResult, JobContext, build_chunk

log = get_logger(__name__)

CAPTION_PROMPT: Final[str] = (
    "Describe this image for an investigation index: visible objects, people, text, "
    "setting and anything identifying."
)
EXIF_DATE_TAGS: Final[tuple[str, ...]] = ("DateTimeOriginal", "DateTimeDigitized", "DateTime")
EXIF_DATE_FORMATS: Final[tuple[str, ...]] = ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S")
EXIF_IFD_POINTER: Final[int] = 0x8769
MAX_EXIF_VALUE_CHARS: Final[int] = 200


class ImagePipeline(BasePipeline):
    """Single-image ingestion."""

    modality = Modality.IMAGE

    async def run(self, asset: Asset, job_ctx: JobContext) -> IngestResult:
        path = job_ctx.require_path()
        warnings: list[str] = []
        await self.report(job_ctx, STAGE_EXTRACT, 0.15, "reading image metadata")

        properties, captured_at = await asyncio.to_thread(read_image_metadata, path)
        data = await asyncio.to_thread(path.read_bytes)
        analysis = await self._analyse(data, warnings, label=asset.title, job_ctx=job_ctx)

        indexed_asset = asset.model_copy(
            update={
                "metadata": {
                    **asset.metadata,
                    **properties,
                    "caption": analysis.caption,
                    "ocr_characters": len(analysis.ocr_text),
                    "objects": analysis.objects,
                    "captured_at": captured_at.isoformat() if captured_at else None,
                },
            }
        )
        chunk = build_chunk(
            indexed_asset,
            ordinal=0,
            text=_image_text(indexed_asset, analysis, properties),
            modality=Modality.IMAGE,
            locator=ImageLocator(image_id=indexed_asset.asset_id),
            metadata={
                "caption": analysis.caption,
                "ocr": analysis.ocr_text,
                "objects": analysis.objects,
                "has_image_vector": analysis.vector is not None,
                "width": properties.get("width"),
                "height": properties.get("height"),
            },
            occurred_at=captured_at,
        )
        return await self.finalise(
            indexed_asset,
            [chunk],
            job_ctx,
            image_vectors={chunk.chunk_id: analysis.vector} if analysis.vector else {},
            warnings=warnings,
            metrics={"ocr_characters": len(analysis.ocr_text), "captioned": bool(analysis.caption)},
        )

    async def _analyse(
        self, data: bytes, warnings: list[str], *, label: str, job_ctx: JobContext
    ) -> _ImageAnalysis:
        """OCR, caption and multimodal embedding, each degrading independently."""
        ocr_text = await self.ocr_text(data, warnings, label=label)
        await self.report(job_ctx, STAGE_EXTRACT, 0.4, "captioning image")
        description = await self.describe(data, warnings, prompt=CAPTION_PROMPT, label=label)
        vector = await self.embed_image(data, warnings, label=label)
        caption = description.caption.strip() if description else ""
        detected = (description.detected_text.strip() if description else "") or ocr_text
        objects = list(description.objects) if description else []
        return _ImageAnalysis(caption=caption, ocr_text=ocr_text, detected_text=detected,
                              objects=objects, vector=vector)


@dataclass(frozen=True)
class _ImageAnalysis:
    caption: str
    ocr_text: str
    detected_text: str
    objects: list[str]
    vector: list[float] | None


def read_image_metadata(path: Path) -> tuple[dict[str, Any], datetime | None]:
    """Dimensions, format and a whitelisted EXIF view plus the capture time."""
    try:
        with Image.open(path) as image:
            properties: dict[str, Any] = {
                "width": image.width,
                "height": image.height,
                "format": image.format,
                "mode": image.mode,
            }
            exif = _exif_dictionary(image)
    except (UnidentifiedImageError, OSError) as exc:
        log.warning("image.metadata_failed", path=str(path), error=str(exc))
        return {"width": None, "height": None, "format": None, "mode": None}, None

    if exif:
        properties["exif"] = exif
    return properties, _captured_at(exif)


def _exif_dictionary(image: Image.Image) -> dict[str, Any]:
    try:
        raw = image.getexif()
    except Exception as exc:  # pragma: no cover - broken exif block
        log.warning("image.exif_failed", error=str(exc))
        return {}
    if not raw:
        return {}
    values = {ExifTags.TAGS.get(tag, str(tag)): value for tag, value in raw.items()}
    try:
        detail = raw.get_ifd(EXIF_IFD_POINTER)
    except Exception:  # pragma: no cover - some files have no Exif IFD
        detail = {}
    values.update({ExifTags.TAGS.get(tag, str(tag)): value for tag, value in (detail or {}).items()})
    return {key: text for key, value in values.items() if (text := _scalar(value))}


def _scalar(value: Any) -> str | None:
    if isinstance(value, bytes):
        return None
    if isinstance(value, (int, float, str)):
        text = str(value).strip()
        return text[:MAX_EXIF_VALUE_CHARS] or None
    return None


def _captured_at(exif: Mapping[str, Any]) -> datetime | None:
    for tag in EXIF_DATE_TAGS:
        raw = str(exif.get(tag, "")).strip()
        for pattern in EXIF_DATE_FORMATS:
            try:
                return datetime.strptime(raw, pattern).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def _image_text(asset: Asset, analysis: _ImageAnalysis, properties: Mapping[str, Any]) -> str:
    """Compose the lexical/semantic body for an image - never empty."""
    parts = [f"Image: {asset.title}"]
    if analysis.caption:
        parts.append(analysis.caption)
    if analysis.detected_text:
        parts.append(f"Text in image: {analysis.detected_text}")
    if analysis.objects:
        parts.append(f"Objects: {', '.join(analysis.objects)}")
    width, height = properties.get("width"), properties.get("height")
    if width and height:
        parts.append(f"Dimensions: {width}x{height}")
    return "\n".join(parts).strip()
