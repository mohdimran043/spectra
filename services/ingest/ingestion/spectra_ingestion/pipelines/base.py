"""Shared pipeline machinery: job context, result type and the common steps.

Each modality pipeline owns *extraction*; everything after that (entity
annotation, embedding, indexing) is identical and lives here so the five
pipelines cannot drift apart.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from spectra_ai_core.gateway import ModelGateway
from spectra_ai_core.interfaces import VisionDescription
from spectra_config.logging import get_logger
from spectra_schemas import Asset, Chunk, Locator, Modality, Provenance, chunk_id

from ..entity_hook import EntityExtractor, RegexEntityExtractor, annotate_chunks
from ..indexer import Indexer, IndexReport

log = get_logger(__name__)

STAGE_EXTRACT: Final[str] = "extracting"
STAGE_EMBED: Final[str] = "embedding"
STAGE_INDEX: Final[str] = "indexing"

StageReporter = Callable[[str, float, str], Awaitable[None]]


@dataclass(frozen=True)
class JobContext:
    """Everything a pipeline needs that is not part of the asset itself."""

    job_id: str
    source_id: str
    local_path: Path | None = None
    permissions: tuple[str, ...] = ("admin", "analyst", "viewer")
    payload: Mapping[str, Any] = field(default_factory=dict)
    report: StageReporter | None = None

    def require_path(self) -> Path:
        if self.local_path is None or not self.local_path.exists():
            raise FileNotFoundError(f"job {self.job_id}: no local file to process")
        return self.local_path


@dataclass(frozen=True)
class IngestResult:
    """What one pipeline run produced.  Chunks live in storage, not in here."""

    asset: Asset
    chunk_count: int = 0
    image_vector_count: int = 0
    entity_count: int = 0
    warnings: tuple[str, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)


class BasePipeline(ABC):
    """Common behaviour for every modality pipeline."""

    modality: Modality = Modality.DOCUMENT

    def __init__(
        self,
        indexer: Indexer,
        gateway: ModelGateway,
        *,
        entity_extractor: EntityExtractor | None = None,
    ) -> None:
        self._indexer = indexer
        self._gateway = gateway
        self._entities = entity_extractor or RegexEntityExtractor()

    @abstractmethod
    async def run(self, asset: Asset, job_ctx: JobContext) -> IngestResult: ...

    # -- shared steps -----------------------------------------------------
    async def report(self, ctx: JobContext, stage: str, progress: float, message: str = "") -> None:
        if ctx.report is None:
            return
        try:
            await ctx.report(stage, progress, message)
        except Exception as exc:  # progress reporting must never fail a job
            log.warning("pipeline.report_failed", job_id=ctx.job_id, stage=stage, error=str(exc))

    async def finalise(
        self,
        asset: Asset,
        chunks: Sequence[Chunk],
        ctx: JobContext,
        *,
        image_vectors: Mapping[str, Sequence[float]] | None = None,
        warnings: Sequence[str] = (),
        metrics: Mapping[str, Any] | None = None,
        replace: bool = True,
    ) -> IngestResult:
        """Annotate entities, index everything and build the result."""
        await self.report(ctx, STAGE_EMBED, 0.7, f"indexing {len(chunks)} chunks")
        annotated, entities, links = annotate_chunks(chunks, self._entities)
        report = await self._indexer.index_asset(
            asset,
            annotated,
            image_vectors=image_vectors,
            entities=entities,
            links=links,
            replace=replace,
        )
        await self.report(ctx, STAGE_INDEX, 0.95, f"indexed {report.chunk_count} chunks")
        return _result(asset, report, warnings, metrics)

    async def ocr_text(self, image: bytes, warnings: list[str], *, label: str = "") -> str:
        """OCR one image, degrading to empty text with a recorded reason."""
        if not image:
            return ""
        try:
            result = await self._gateway.ocr(image)
        except Exception as exc:
            warnings.append(f"ocr_failed{_suffix(label)}: {exc}")
            log.warning("pipeline.ocr_failed", label=label, error=str(exc))
            return ""
        return result.text.strip()

    async def describe(self, image: bytes, warnings: list[str], *, prompt: str = "", label: str = "") -> VisionDescription | None:
        try:
            return await self._gateway.describe_image(image, prompt)
        except Exception as exc:
            warnings.append(f"vision_failed{_suffix(label)}: {exc}")
            log.warning("pipeline.vision_failed", label=label, error=str(exc))
            return None

    async def embed_image(self, image: bytes, warnings: list[str], *, label: str = "") -> list[float] | None:
        try:
            result = await self._gateway.embed_images([image])
        except Exception as exc:
            warnings.append(f"image_embedding_failed{_suffix(label)}: {exc}")
            log.warning("pipeline.image_embedding_failed", label=label, error=str(exc))
            return None
        vectors = list(result.vectors)
        return list(vectors[0]) if vectors else None


def build_chunk(
    asset: Asset,
    *,
    ordinal: int,
    text: str,
    modality: Modality,
    locator: Locator,
    title: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    occurred_at: datetime | None = None,
    discriminator: str = "",
) -> Chunk:
    """Build a fully-provenanced chunk (ids are deterministic, so re-ingest is stable)."""
    provenance = Provenance(
        source_id=asset.source_id,
        modality=modality,
        object_uri=asset.object_uri,
        locator=locator,
        content_hash=asset.content_hash or None,
        version=asset.version,
        version_status=asset.version_status,
        created_at=asset.created_at,
        modified_at=asset.modified_at,
        ingested_at=asset.ingested_at,
    )
    return Chunk(
        chunk_id=chunk_id(asset.asset_id, ordinal, discriminator),
        asset_id=asset.asset_id,
        source_id=asset.source_id,
        modality=modality,
        text=text,
        title=title or asset.title,
        ordinal=ordinal,
        provenance=provenance.model_dump(mode="json"),
        metadata=dict(metadata or {}),
        occurred_at=occurred_at,
        permissions=list(asset.permissions),
    )


def merge_metrics(report: IndexReport, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "chunks": report.chunk_count,
        "text_vectors": report.text_vectors,
        "image_vectors": report.image_vectors,
        "lexical_documents": report.lexical_documents,
        "entities": report.entities,
        "index_version": report.index_version,
        **dict(extra or {}),
    }


def _result(
    asset: Asset,
    report: IndexReport,
    warnings: Sequence[str],
    metrics: Mapping[str, Any] | None,
) -> IngestResult:
    return IngestResult(
        asset=asset,
        chunk_count=report.chunk_count,
        image_vector_count=report.image_vectors,
        entity_count=report.entities,
        warnings=(*warnings, *report.warnings),
        metrics=merge_metrics(report, metrics),
    )


def _suffix(label: str) -> str:
    return f" [{label}]" if label else ""
