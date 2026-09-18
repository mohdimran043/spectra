"""Speech-shaped placeholder audio plus authoritative transcript sidecars.

No offline text-to-speech model is assumed, so the WAV files are honest
placeholders: a voiced carrier per speaker, amplitude-modulated at a syllable
rate, with real silence between turns.  The *transcript* is the authoritative
content and ships beside every clip as ``<name>.transcript.json``.  On a
machine with a working ASR model the production pipeline transcribes the audio
instead of reading the sidecar - see demo-data/README.md.
"""

from __future__ import annotations

import json
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Sequence

import numpy as np

from .constants import (
    AUDIO_CHANNELS,
    AUDIO_PEAK_AMPLITUDE,
    AUDIO_SAMPLE_RATE,
    AUDIO_SAMPLE_WIDTH_BYTES,
    INTER_SEGMENT_SILENCE_SECONDS,
    MIN_SEGMENT_SECONDS,
    SPEAKER_BASE_FREQUENCIES_HZ,
    SYLLABLE_RATE_HZ,
    WORDS_PER_SECOND,
)

TRANSCRIPT_SUFFIX: Final[str] = ".transcript.json"
MEDIA_TYPE_WAV: Final[str] = "audio/wav"
#: Harmonic weights that make the placeholder sound voiced rather than pure-tone.
HARMONICS: Final[tuple[tuple[int, float], ...]] = ((1, 1.0), (2, 0.45), (3, 0.22), (5, 0.08))
#: Fraction of the syllable envelope that stays open, so turns are not buzzy.
ENVELOPE_FLOOR: Final[float] = 0.18
FADE_SECONDS: Final[float] = 0.02


@dataclass(frozen=True)
class Segment:
    """One transcript turn with the seconds it occupies in the clip."""

    start: float
    end: float
    speaker: str
    text: str

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 3)

    def as_dict(self) -> dict[str, object]:
        return {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "speaker": self.speaker,
            "text": self.text,
        }


def layout_segments(turns: Sequence[tuple[str, str]], start_at: float = 0.0) -> tuple[Segment, ...]:
    """Place (speaker, text) turns on a timeline at a natural speaking rate."""
    cursor = start_at
    segments: list[Segment] = []
    for speaker, text in turns:
        words = max(1, len(text.split()))
        duration = max(MIN_SEGMENT_SECONDS, round(words / WORDS_PER_SECOND, 2))
        segments.append(Segment(start=round(cursor, 3), end=round(cursor + duration, 3),
                                speaker=speaker, text=text))
        cursor += duration + INTER_SEGMENT_SILENCE_SECONDS
    return tuple(segments)


def _speaker_frequency(speaker: str) -> float:
    index = sum(ord(character) for character in speaker) % len(SPEAKER_BASE_FREQUENCIES_HZ)
    return SPEAKER_BASE_FREQUENCIES_HZ[index]


def _voiced(duration: float, frequency: float) -> np.ndarray:
    samples = max(1, int(duration * AUDIO_SAMPLE_RATE))
    time = np.arange(samples, dtype=np.float64) / AUDIO_SAMPLE_RATE
    wave_form = np.zeros(samples, dtype=np.float64)
    for harmonic, weight in HARMONICS:
        wave_form += weight * np.sin(2.0 * np.pi * frequency * harmonic * time)
    envelope = ENVELOPE_FLOOR + (1.0 - ENVELOPE_FLOOR) * (
        0.5 * (1.0 - np.cos(2.0 * np.pi * SYLLABLE_RATE_HZ * time))
    )
    wave_form *= envelope
    fade = max(1, int(FADE_SECONDS * AUDIO_SAMPLE_RATE))
    ramp = np.linspace(0.0, 1.0, fade)
    wave_form[:fade] *= ramp
    wave_form[-fade:] *= ramp[::-1]
    peak = float(np.max(np.abs(wave_form))) or 1.0
    return wave_form / peak


def render_samples(segments: Sequence[Segment], total_seconds: float | None = None) -> np.ndarray:
    """Build the whole clip as int16 samples, silence included."""
    end = total_seconds if total_seconds is not None else (segments[-1].end if segments else 1.0)
    length = max(1, int(end * AUDIO_SAMPLE_RATE))
    track = np.zeros(length, dtype=np.float64)
    for segment in segments:
        start_index = int(segment.start * AUDIO_SAMPLE_RATE)
        block = _voiced(segment.duration, _speaker_frequency(segment.speaker))
        stop_index = min(length, start_index + block.size)
        if stop_index <= start_index:
            continue
        track[start_index:stop_index] += block[: stop_index - start_index]
    peak = float(np.max(np.abs(track))) or 1.0
    return np.int16(np.clip(track / peak, -1.0, 1.0) * AUDIO_PEAK_AMPLITUDE)


def write_wav(path: Path, segments: Sequence[Segment], total_seconds: float | None = None) -> float:
    """Write a real RIFF/WAVE file and return its duration in seconds."""
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = render_samples(segments, total_seconds)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(AUDIO_CHANNELS)
        handle.setsampwidth(AUDIO_SAMPLE_WIDTH_BYTES)
        handle.setframerate(AUDIO_SAMPLE_RATE)
        handle.writeframes(samples.tobytes())
    return round(samples.size / AUDIO_SAMPLE_RATE, 3)


def write_transcript(path: Path, media_id: str, segments: Sequence[Segment], *, source: str) -> None:
    """Write the authoritative transcript sidecar."""
    payload = {
        "media_id": media_id,
        "source": source,
        "is_ground_truth": True,
        "segments": [segment.as_dict() for segment in segments],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def transcript_text(segments: Sequence[Segment]) -> str:
    return "\n".join(f"{segment.speaker}: {segment.text}" for segment in segments)


def find_span(segments: Sequence[Segment], needle: str) -> tuple[float, float] | None:
    """Seconds range of the first turn containing ``needle`` - used for answer keys."""
    lowered = needle.lower()
    for segment in segments:
        if lowered in segment.text.lower():
            return (segment.start, segment.end)
    return None
