"""faster-whisper speech-to-text with real word-aligned segment timestamps."""

from __future__ import annotations

import asyncio
import math
import time
from pathlib import Path
from typing import Any

from spectra_config.logging import get_logger

from .. import cuda_libs
from ..interfaces import SpeechProvider, TranscriptionResult, TranscriptSegment
from .hf_assets import asset_status, package_missing

log = get_logger(__name__)

RUNTIME_NAME = "faster_whisper"
PACKAGE_NAME = "faster_whisper"
REPO_TEMPLATE = "Systran/faster-whisper-{size}"
CPU_COMPUTE_TYPE = "int8"
CUDA_COMPUTE_TYPE = "float16"
GPU_ONLY_COMPUTE_TYPES = frozenset({"float16", "int8_float16"})
DEFAULT_BEAM_SIZE = 5

# Heuristic speaker segmentation - see :meth:`FasterWhisperSpeech.transcribe`.
DIARISATION_GAP_SECONDS = 1.5
MAX_HEURISTIC_SPEAKERS = 4
SPEAKER_LABEL = "SPEAKER_{index}"


def resolve_repo(model: str) -> str:
    """Map a whisper size name (``large-v3``) to its hub repository."""
    if "/" in model or Path(model).expanduser().is_dir():
        return model
    try:
        from faster_whisper.utils import _MODELS  # type: ignore[attr-defined]

        return str(_MODELS.get(model, REPO_TEMPLATE.format(size=model)))
    except Exception:
        return REPO_TEMPLATE.format(size=model)


def resolve_compute_type(device: str, requested: str | None) -> str:
    """CPU cannot run the float16 kernels, so downgrade rather than crash at load."""
    default = CUDA_COMPUTE_TYPE if device == "cuda" else CPU_COMPUTE_TYPE
    compute_type = requested or default
    if device != "cuda" and compute_type in GPU_ONLY_COMPUTE_TYPES:
        return CPU_COMPUTE_TYPE
    return compute_type


class FasterWhisperSpeech(SpeechProvider):
    """Transcription via CTranslate2 whisper weights.

    ``diarize=True`` applies *heuristic pause-based speaker segmentation*: a new
    ``SPEAKER_n`` label starts whenever the silence between consecutive segments
    exceeds :data:`DIARISATION_GAP_SECONDS`.  It is deliberately **not** a
    diarisation model - there is no voice embedding, clustering or speaker
    identity involved - so labels indicate turn boundaries, not people.
    """

    runtime_name = RUNTIME_NAME

    def __init__(self, model: str, device: str = "cpu", **options: Any) -> None:
        super().__init__(model, device, **options)
        self.compute_type = resolve_compute_type(device, options.get("compute_type"))
        self.beam_size = int(options.get("beam_size") or DEFAULT_BEAM_SIZE)
        self._model: Any | None = None

    async def available(self) -> tuple[bool, str]:
        missing = package_missing(PACKAGE_NAME)
        if missing:
            return False, missing
        # CTranslate2 dlopens cuDNN itself and *aborts the process* when it
        # cannot find it, so this has to be decided before the candidate is
        # selected - not caught afterwards.
        if self.device == "cuda":
            status = cuda_libs.probe()
            if not status.ready:
                return False, (
                    "CUDA requested but the native cuDNN/cuBLAS libraries are not loadable "
                    f"({status.detail}); install nvidia-cudnn-cu12 or use the CPU candidate"
                )
        # asset_status may touch the network, so keep it off the event loop.
        return await asyncio.to_thread(asset_status, resolve_repo(self.model), PACKAGE_NAME)

    async def load(self) -> None:
        if self._model is not None:
            return
        ok, reason = await self.available()
        if not ok:
            raise RuntimeError(f"cannot load whisper {self.model}: {reason}")
        self._model = await asyncio.to_thread(self._construct)
        await super().load()
        log.info("whisper.loaded", model=self.model, device=self.device, compute_type=self.compute_type)

    def _construct(self) -> Any:
        # Preload again here: the symbols must be resident in *this* process
        # before CTranslate2 initialises its CUDA backend.
        if self.device == "cuda":
            cuda_libs.ensure_loaded()
        from faster_whisper import WhisperModel

        return WhisperModel(self.model, device=self.device, compute_type=self.compute_type)

    async def unload(self) -> None:
        self._model = None
        await super().unload()

    async def transcribe(
        self, audio_path: str, *, language: str | None = None, diarize: bool = False
    ) -> TranscriptionResult:
        path = Path(audio_path)
        if not path.is_file():
            raise FileNotFoundError(f"audio file not found: {audio_path}")
        await self.load()
        started = time.perf_counter()
        segments, info = await asyncio.to_thread(self._run, str(path), language)
        labelled = _label_speakers(segments) if diarize else segments
        return TranscriptionResult(
            segments=labelled,
            language=str(getattr(info, "language", language or "en") or "en"),
            duration=float(getattr(info, "duration", 0.0) or 0.0),
            model=self.model,
            runtime=RUNTIME_NAME,
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )

    def _run(self, path: str, language: str | None) -> tuple[list[TranscriptSegment], Any]:
        model = self._model
        if model is None:  # pragma: no cover - load() raises first
            raise RuntimeError(f"whisper {self.model} is not loaded")
        raw, info = model.transcribe(
            path, language=language, beam_size=self.beam_size, word_timestamps=True
        )
        return [_to_segment(item) for item in raw], info


def _to_segment(raw: Any) -> TranscriptSegment:
    return TranscriptSegment(
        start=float(getattr(raw, "start", 0.0) or 0.0),
        end=float(getattr(raw, "end", 0.0) or 0.0),
        text=str(getattr(raw, "text", "") or "").strip(),
        confidence=_confidence(getattr(raw, "avg_logprob", None)),
    )


def _confidence(avg_logprob: float | None) -> float:
    if avg_logprob is None:
        return 1.0
    return round(min(1.0, max(0.0, math.exp(float(avg_logprob)))), 4)


def _label_speakers(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    """Best-effort turn labelling from silence gaps.  Not speaker identification."""
    labelled: list[TranscriptSegment] = []
    speaker_index = 1
    previous_end: float | None = None
    for segment in segments:
        if previous_end is not None and segment.start - previous_end >= DIARISATION_GAP_SECONDS:
            speaker_index = speaker_index % MAX_HEURISTIC_SPEAKERS + 1
        labelled.append(
            TranscriptSegment(
                start=segment.start,
                end=segment.end,
                text=segment.text,
                speaker=SPEAKER_LABEL.format(index=speaker_index),
                confidence=segment.confidence,
            )
        )
        previous_end = segment.end
    return labelled
