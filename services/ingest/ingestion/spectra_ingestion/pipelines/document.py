"""Document pipeline: detect -> extract -> OCR inline images -> chunk -> index."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from spectra_ai_core.gateway import ModelGateway
from spectra_config.logging import get_logger
from spectra_schemas import Asset, Chunk, DocumentLocator, Modality

from ..chunking import DEFAULT_OVERLAP_RATIO, DEFAULT_TARGET_TOKENS, ChunkDraft, chunk_blocks
from ..entity_hook import EntityExtractor
from ..extractors import ExtractedBlock, ExtractionError, detect_media_type, get_extractor
from ..extractors import pdf as pdf_extractor
from ..indexer import Indexer
from .base import STAGE_EXTRACT, BasePipeline, IngestResult, JobContext, build_chunk

log = get_logger(__name__)

PDF_MEDIA_TYPE: Final[str] = "application/pdf"
MAX_OCR_IMAGES: Final[int] = 20


class UnsupportedDocument(RuntimeError):
    """No parser is registered for this media type."""


class DocumentPipeline(BasePipeline):
    """PDF / Office / plain-text ingestion with page and section provenance."""

    modality = Modality.DOCUMENT

    def __init__(
        self,
        indexer: Indexer,
        gateway: ModelGateway,
        *,
        entity_extractor: EntityExtractor | None = None,
        target_tokens: int = DEFAULT_TARGET_TOKENS,
        overlap_ratio: float = DEFAULT_OVERLAP_RATIO,
    ) -> None:
        super().__init__(indexer, gateway, entity_extractor=entity_extractor)
        self._target_tokens = target_tokens
        self._overlap_ratio = overlap_ratio

    async def run(self, asset: Asset, job_ctx: JobContext) -> IngestResult:
        path = job_ctx.require_path()
        warnings: list[str] = []
        media_type, _kind = detect_media_type(path, asset.media_type)
        extractor = get_extractor(media_type)
        if extractor is None:
            raise UnsupportedDocument(f"no extractor for media type {media_type}")

        await self.report(job_ctx, STAGE_EXTRACT, 0.15, f"parsing {media_type}")
        try:
            blocks = await asyncio.to_thread(extractor, path)
        except ExtractionError as exc:
            raise UnsupportedDocument(str(exc)) from exc

        if media_type == PDF_MEDIA_TYPE:
            ocr_blocks = await self._ocr_embedded_images(path, blocks, warnings)
            blocks = [*blocks, *ocr_blocks]

        await self.report(job_ctx, STAGE_EXTRACT, 0.45, f"{len(blocks)} blocks extracted")
        drafts = chunk_blocks(blocks, target_tokens=self._target_tokens, overlap_ratio=self._overlap_ratio)
        indexed_asset = asset.model_copy(
            update={
                "media_type": media_type,
                "page_count": _page_count(blocks, media_type, path),
                "metadata": {**asset.metadata, "block_count": len(blocks), "chunk_count": len(drafts)},
            }
        )
        chunks = [self._chunk(indexed_asset, draft) for draft in drafts]
        return await self.finalise(
            indexed_asset,
            chunks,
            job_ctx,
            warnings=warnings,
            metrics={"blocks": len(blocks), "media_type": media_type},
        )

    def _chunk(self, asset: Asset, draft: ChunkDraft) -> Chunk:
        locator = DocumentLocator(
            document_id=asset.asset_id,
            page=draft.page,
            section=draft.section,
            paragraph=draft.block_ordinals[0] if draft.block_ordinals else None,
            bbox=draft.bbox,
        )
        return build_chunk(
            asset,
            ordinal=draft.ordinal,
            text=draft.text,
            modality=Modality.DOCUMENT,
            locator=locator,
            metadata={
                "kind": draft.kind,
                "token_count": draft.token_count,
                "block_ordinals": list(draft.block_ordinals),
                **dict(draft.metadata),
            },
        )

    async def _ocr_embedded_images(
        self, path: Path, blocks: Sequence[ExtractedBlock], warnings: list[str]
    ) -> list[ExtractedBlock]:
        try:
            images = await asyncio.to_thread(pdf_extractor.extract_images, path, limit=MAX_OCR_IMAGES)
        except ExtractionError as exc:
            warnings.append(f"pdf_image_extraction_failed: {exc}")
            return []

        ocr_blocks: list[ExtractedBlock] = []
        base_ordinal = len(blocks)
        for image in images:
            text = await self.ocr_text(image.data, warnings, label=f"page {image.page}")
            if not text:
                continue
            ocr_blocks.append(
                ExtractedBlock(
                    text=text,
                    kind="ocr",
                    page=image.page,
                    section=_section_for_page(blocks, image.page),
                    ordinal=base_ordinal + len(ocr_blocks),
                    bbox=image.bbox,
                    metadata={"origin": "embedded_image", "image_ordinal": image.ordinal},
                )
            )
        return ocr_blocks


def _section_for_page(blocks: Sequence[ExtractedBlock], page: int | None) -> str | None:
    for block in reversed(blocks):
        if block.page == page and block.section:
            return block.section
    return None


def _page_count(blocks: Sequence[ExtractedBlock], media_type: str, path: Path) -> int | None:
    if media_type == PDF_MEDIA_TYPE:
        try:
            return pdf_extractor.page_count(path)
        except ExtractionError as exc:
            log.warning("document.page_count_failed", error=str(exc))
    pages = [block.page for block in blocks if block.page is not None]
    return max(pages) if pages else None
