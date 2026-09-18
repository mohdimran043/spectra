"""Video pipeline: transcript + scenes + keyframes, all resolved at ingestion.

Nothing in here may run at query time: a search hit points at a scene that was
already detected, captioned, OCR-ed and embedded while the video was ingested.

Scene detection degrades in three steps - PySceneDetect when installed, then an
ffmpeg ``select='gt(scene,N)'`` pass, then uniform intervals - so a video is
always segmented even on a bare machine.
"""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from spectra_ai_core.gateway import ModelGateway
from spectra_config.logging import get_logger
from spectra_schemas import Asset, Chunk, Modality, VideoLocator

from ..chunking import DEFAULT_TARGET_TOKENS, TranscriptWindow, merge_transcript_segments, window_text
from ..entity_hook import EntityExtractor
from ..indexer import Indexer
from ..media import (
    MediaToolError,
    detect_scene_cuts,
    duration_seconds,
    extract_audio,
    extract_frame,
    probe,
    scenes_from_cuts,
    uniform_scenes,
    video_properties,
)
from .audio import transcript_metadata
from .base import STAGE_EXTRACT, BasePipeline, IngestResult, JobContext, build_chunk

log = get_logger(__name__)

SCENE_PROMPT: Final[str] = (
    "Describe this video frame for an investigation index: people, objects, on-screen "
    "text, location and what is happening."
)
MAX_ANALYSED_SCENES: Final[int] = 24
PYSCENEDETECT_THRESHOLD: Final[float] = 27.0


class VideoPipeline(BasePipeline):
    """Transcript chunks plus scene chunks with captions, OCR and image vectors."""

    modality = Modality.VIDEO

    def __init__(
        self,
        indexer: Indexer,
        gateway: ModelGateway,
        *,
        entity_extractor: EntityExtractor | None = None,
        target_tokens: int = DEFAULT_TARGET_TOKENS,
        max_scenes: int = MAX_ANALYSED_SCENES,
    ) -> None:
        super().__init__(indexer, gateway, entity_extractor=entity_extractor)
        self._target_tokens = target_tokens
        self._max_scenes = max_scenes

    async def run(self, asset: Asset, job_ctx: JobContext) -> IngestResult:
        path = job_ctx.require_path()
        warnings: list[str] = []
        await self.report(job_ctx, STAGE_EXTRACT, 0.08, "probing video")
        metadata, duration, properties = await self._probe(path, warnings)

        windows = await self._transcribe(path, properties, warnings, job_ctx)
        await self.report(job_ctx, STAGE_EXTRACT, 0.4, "detecting scenes")
        scenes, detector = await self._scenes(path, duration or 0.0, warnings)

        indexed_asset = asset.model_copy(
            update={
                "duration_seconds": duration,
                "metadata": {
                    **asset.metadata,
                    **metadata,
                    **properties,
                    "scene_count": len(scenes),
                    "scene_detector": detector,
                    "transcript_windows": len(windows),
                },
            }
        )
        chunks = [self._transcript_chunk(indexed_asset, window) for window in windows]
        scene_chunks, vectors = await self._scene_chunks(
            indexed_asset, path, scenes, windows, len(chunks), warnings, job_ctx
        )
        return await self.finalise(
            indexed_asset,
            [*chunks, *scene_chunks],
            job_ctx,
            image_vectors=vectors,
            warnings=warnings,
            metrics={
                "duration_seconds": duration,
                "transcript_windows": len(windows),
                "scenes": len(scenes),
                "analysed_scenes": len(scene_chunks),
                "scene_detector": detector,
            },
        )

    # -- steps ------------------------------------------------------------
    async def _probe(
        self, path: Path, warnings: list[str]
    ) -> tuple[dict[str, Any], float | None, dict[str, Any]]:
        try:
            metadata = await probe(path)
        except MediaToolError as exc:
            warnings.append(f"ffprobe_failed: {exc}")
            return {}, None, {"has_audio": False}
        summary = {
            "container": (metadata.get("format") or {}).get("format_name"),
            "bit_rate": (metadata.get("format") or {}).get("bit_rate"),
        }
        return summary, duration_seconds(metadata), video_properties(metadata)

    async def _transcribe(
        self, path: Path, properties: dict[str, Any], warnings: list[str], job_ctx: JobContext
    ) -> list[TranscriptWindow]:
        if not properties.get("has_audio"):
            return []
        await self.report(job_ctx, STAGE_EXTRACT, 0.18, "transcribing video audio")
        with tempfile.TemporaryDirectory(prefix="spectra-audio-") as workdir:
            wav = Path(workdir) / "audio.wav"
            try:
                await extract_audio(path, wav)
            except MediaToolError as exc:
                warnings.append(f"audio_demux_failed: {exc}")
                return []
            try:
                transcription = await self._gateway.transcribe(str(wav))
            except Exception as exc:
                warnings.append(f"transcription_failed: {exc}")
                log.warning("video.transcription_failed", path=str(path), error=str(exc))
                return []
        return merge_transcript_segments(transcription.segments, target_tokens=self._target_tokens)

    async def _scenes(
        self, path: Path, duration: float, warnings: list[str]
    ) -> tuple[list[tuple[float, float]], str]:
        scenes = await _pyscenedetect_scenes(path, warnings)
        if scenes:
            return scenes[: self._max_scenes], "pyscenedetect"
        try:
            cuts = await detect_scene_cuts(path)
            scenes = scenes_from_cuts(cuts, duration) if cuts else []
        except MediaToolError as exc:
            warnings.append(f"scene_detection_failed: {exc}")
            scenes = []
        if scenes:
            return scenes[: self._max_scenes], "ffmpeg_select"
        return uniform_scenes(duration)[: self._max_scenes], "uniform"

    async def _scene_chunks(
        self,
        asset: Asset,
        path: Path,
        scenes: Sequence[tuple[float, float]],
        windows: Sequence[TranscriptWindow],
        ordinal_offset: int,
        warnings: list[str],
        job_ctx: JobContext,
    ) -> tuple[list[Chunk], dict[str, list[float]]]:
        chunks: list[Chunk] = []
        vectors: dict[str, list[float]] = {}
        for index, (start, end) in enumerate(scenes[: self._max_scenes]):
            await self.report(
                job_ctx, STAGE_EXTRACT, 0.4 + 0.25 * (index + 1) / max(len(scenes), 1), f"scene {index + 1}"
            )
            chunk, vector = await self._scene_chunk(
                asset, path, index, start, end, windows, ordinal_offset + len(chunks), warnings
            )
            if chunk is None:
                continue
            chunks.append(chunk)
            if vector:
                vectors[chunk.chunk_id] = vector
        return chunks, vectors

    async def _scene_chunk(
        self,
        asset: Asset,
        path: Path,
        index: int,
        start: float,
        end: float,
        windows: Sequence[TranscriptWindow],
        ordinal: int,
        warnings: list[str],
    ) -> tuple[Chunk | None, list[float] | None]:
        label = f"scene {index + 1}"
        frame = await self._keyframe(path, start, end, label, warnings)
        ocr_text, caption, vector = await self._analyse_frame(frame, label, warnings)
        spoken = window_text(windows, start, end)
        text = _scene_text(start, end, spoken, caption, ocr_text)
        if not text:
            return None, None

        chunk = build_chunk(
            asset,
            ordinal=ordinal,
            text=text,
            modality=Modality.VIDEO,
            locator=VideoLocator(
                video_id=asset.asset_id,
                scene_id=f"scene_{index:04d}",
                frame_id=f"frame_{index:04d}",
                start_seconds=start,
                end_seconds=end,
            ),
            metadata={
                "start_seconds": start,
                "end_seconds": end,
                "caption": caption,
                "ocr": ocr_text,
                "transcript": spoken,
                "has_image_vector": vector is not None,
            },
            discriminator="scene",
        )
        return chunk, vector

    async def _keyframe(
        self, path: Path, start: float, end: float, label: str, warnings: list[str]
    ) -> bytes:
        try:
            return await extract_frame(path, (start + end) / 2.0)
        except MediaToolError as exc:
            warnings.append(f"keyframe_failed [{label}]: {exc}")
            return b""

    async def _analyse_frame(
        self, frame: bytes, label: str, warnings: list[str]
    ) -> tuple[str, str, list[float] | None]:
        """OCR, caption and embed one keyframe; each step degrades on its own."""
        if not frame:
            return "", "", None
        ocr_text = await self.ocr_text(frame, warnings, label=label)
        description = await self.describe(frame, warnings, prompt=SCENE_PROMPT, label=label)
        vector = await self.embed_image(frame, warnings, label=label)
        return ocr_text, description.caption.strip() if description else "", vector

    def _transcript_chunk(self, asset: Asset, window: TranscriptWindow) -> Chunk:
        locator = VideoLocator(
            video_id=asset.asset_id,
            scene_id=None,
            frame_id=None,
            start_seconds=window.start_seconds,
            end_seconds=window.end_seconds,
        )
        return build_chunk(
            asset,
            ordinal=window.ordinal,
            text=window.text,
            modality=Modality.VIDEO,
            locator=locator,
            metadata={**transcript_metadata(window), "origin": "transcript"},
            discriminator="transcript",
        )


async def _pyscenedetect_scenes(path: Path, warnings: list[str]) -> list[tuple[float, float]]:
    """Use PySceneDetect when it is installed; stay silent when it is not."""
    try:
        import scenedetect  # noqa: PLC0415 - optional dependency, imported lazily
    except ImportError:
        return []
    try:
        detected = await asyncio.to_thread(
            scenedetect.detect, str(path), scenedetect.ContentDetector(threshold=PYSCENEDETECT_THRESHOLD)
        )
    except Exception as exc:
        warnings.append(f"pyscenedetect_failed: {exc}")
        log.warning("video.pyscenedetect_failed", path=str(path), error=str(exc))
        return []
    return [(float(start.get_seconds()), float(end.get_seconds())) for start, end in detected]


def _scene_text(start: float, end: float, spoken: str, caption: str, ocr_text: str) -> str:
    parts = [f"Scene {_hms(start)} - {_hms(end)}"]
    if caption:
        parts.append(f"Visual: {caption}")
    if ocr_text:
        parts.append(f"Text on screen: {ocr_text}")
    if spoken:
        parts.append(f"Spoken: {spoken}")
    return "\n".join(parts) if len(parts) > 1 else ""


def _hms(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"
