"""Audio pipeline: probe -> transcribe -> merge segments -> timestamped chunks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from spectra_ai_core.gateway import ModelGateway
from spectra_ai_core.interfaces import TranscriptionResult
from spectra_config.logging import get_logger
from spectra_schemas import Asset, AudioLocator, Chunk, Modality

from ..chunking import DEFAULT_TARGET_TOKENS, TranscriptWindow, merge_transcript_segments
from ..entity_hook import EntityExtractor
from ..indexer import Indexer
from ..media import MediaToolError, duration_seconds, probe
from .base import STAGE_EXTRACT, BasePipeline, IngestResult, JobContext, build_chunk

log = get_logger(__name__)


class AudioPipeline(BasePipeline):
    """Speech-to-text ingestion that keeps the exact span of every chunk."""

    modality = Modality.AUDIO

    def __init__(
        self,
        indexer: Indexer,
        gateway: ModelGateway,
        *,
        entity_extractor: EntityExtractor | None = None,
        target_tokens: int = DEFAULT_TARGET_TOKENS,
    ) -> None:
        super().__init__(indexer, gateway, entity_extractor=entity_extractor)
        self._target_tokens = target_tokens

    async def run(self, asset: Asset, job_ctx: JobContext) -> IngestResult:
        path = job_ctx.require_path()
        warnings: list[str] = []
        await self.report(job_ctx, STAGE_EXTRACT, 0.1, "probing audio")
        metadata, duration = await probe_media(path, warnings)

        await self.report(job_ctx, STAGE_EXTRACT, 0.25, "transcribing audio")
        transcription = await self.transcribe(path, warnings)
        windows = (
            merge_transcript_segments(transcription.segments, target_tokens=self._target_tokens)
            if transcription is not None
            else []
        )
        duration = duration or (transcription.duration if transcription else None)

        indexed_asset = asset.model_copy(
            update={
                "duration_seconds": duration,
                "metadata": {
                    **asset.metadata,
                    **metadata,
                    "language": transcription.language if transcription else None,
                    "segment_count": len(transcription.segments) if transcription else 0,
                    "transcript_windows": len(windows),
                },
            }
        )
        chunks = [self._chunk(indexed_asset, window) for window in windows]
        await self.report(job_ctx, STAGE_EXTRACT, 0.55, f"{len(chunks)} transcript chunks")
        return await self.finalise(
            indexed_asset,
            chunks,
            job_ctx,
            warnings=warnings,
            metrics={"duration_seconds": duration, "windows": len(windows)},
        )

    async def transcribe(self, path: Path, warnings: list[str]) -> TranscriptionResult | None:
        try:
            return await self._gateway.transcribe(str(path))
        except Exception as exc:
            warnings.append(f"transcription_failed: {exc}")
            log.warning("audio.transcription_failed", path=str(path), error=str(exc))
            return None

    def _chunk(self, asset: Asset, window: TranscriptWindow) -> Chunk:
        locator = AudioLocator(
            audio_id=asset.asset_id,
            segment_id=f"seg_{window.ordinal:04d}",
            start_seconds=window.start_seconds,
            end_seconds=window.end_seconds,
            speaker=window.speakers[0] if window.speakers else None,
        )
        return build_chunk(
            asset,
            ordinal=window.ordinal,
            text=window.text,
            modality=Modality.AUDIO,
            locator=locator,
            metadata=transcript_metadata(window),
            discriminator="transcript",
        )


def transcript_metadata(window: TranscriptWindow) -> dict[str, Any]:
    return {
        "start_seconds": window.start_seconds,
        "end_seconds": window.end_seconds,
        "speakers": list(window.speakers),
        "segment_count": window.segment_count,
        "token_count": window.token_count,
    }


async def probe_media(path: Path, warnings: list[str]) -> tuple[dict[str, Any], float | None]:
    """Probe a media file, degrading to empty metadata with a recorded reason."""
    try:
        metadata = await probe(path)
    except MediaToolError as exc:
        warnings.append(f"ffprobe_failed: {exc}")
        log.warning("media.probe_failed", path=str(path), error=str(exc))
        return {}, None
    return {
        "container": (metadata.get("format") or {}).get("format_name"),
        "bit_rate": (metadata.get("format") or {}).get("bit_rate"),
        "stream_count": len(metadata.get("streams", [])),
    }, duration_seconds(metadata)
