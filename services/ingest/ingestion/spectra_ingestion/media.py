"""ffmpeg / ffprobe helpers.

Every call is an explicit argument list (never a shell string), always has a
timeout, and always raises :class:`MediaToolError` with the tool's own stderr
so a pipeline can record a real reason instead of "video failed".
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Final

from spectra_config.logging import get_logger

log = get_logger(__name__)

FFMPEG: Final[str] = "ffmpeg"
FFPROBE: Final[str] = "ffprobe"
PROBE_TIMEOUT_SECONDS: Final[int] = 60
DEMUX_TIMEOUT_SECONDS: Final[int] = 900
SCENE_TIMEOUT_SECONDS: Final[int] = 900
FRAME_TIMEOUT_SECONDS: Final[int] = 120
AUDIO_SAMPLE_RATE: Final[int] = 16_000
SCENE_THRESHOLD: Final[float] = 0.35
MIN_SCENE_SECONDS: Final[float] = 1.5
MIN_SCENE_FLOOR_SECONDS: Final[float] = 0.25
UNIFORM_SCENE_SECONDS: Final[float] = 10.0
MAX_SCENES: Final[int] = 240

_PTS_TIME: Final[re.Pattern[str]] = re.compile(r"pts_time:(\d+(?:\.\d+)?)")


class MediaToolError(RuntimeError):
    """An external media tool was missing, timed out or exited non-zero."""


def tool_available(name: str) -> bool:
    return shutil.which(name) is not None


async def run_tool(args: list[str], *, timeout: int) -> tuple[bytes, bytes]:
    """Run an external tool, returning ``(stdout, stderr)`` or raising."""
    if not tool_available(args[0]):
        raise MediaToolError(f"{args[0]} is not installed")
    try:
        process = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    except OSError as exc:
        raise MediaToolError(f"cannot start {args[0]}: {exc}") from exc

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise MediaToolError(f"{args[0]} timed out after {timeout}s") from exc

    if process.returncode != 0:
        detail = stderr.decode("utf-8", "replace").strip().splitlines()
        raise MediaToolError(f"{args[0]} exited {process.returncode}: {detail[-1] if detail else 'no output'}")
    return stdout, stderr


async def probe(path: str | Path) -> dict[str, Any]:
    """``ffprobe`` metadata for a media file."""
    args = [
        FFPROBE, "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    stdout, _ = await run_tool(args, timeout=PROBE_TIMEOUT_SECONDS)
    try:
        return json.loads(stdout.decode("utf-8", "replace") or "{}")
    except json.JSONDecodeError as exc:
        raise MediaToolError(f"ffprobe returned invalid json: {exc}") from exc


def duration_seconds(metadata: dict[str, Any]) -> float | None:
    raw = (metadata.get("format") or {}).get("duration")
    value = _as_float(raw)
    if value is not None:
        return value
    for stream in metadata.get("streams", []):
        value = _as_float(stream.get("duration"))
        if value is not None:
            return value
    return None


def first_stream(metadata: dict[str, Any], codec_type: str) -> dict[str, Any] | None:
    for stream in metadata.get("streams", []):
        if stream.get("codec_type") == codec_type:
            return stream
    return None


def video_properties(metadata: dict[str, Any]) -> dict[str, Any]:
    stream = first_stream(metadata, "video") or {}
    return {
        "width": stream.get("width"),
        "height": stream.get("height"),
        "codec": stream.get("codec_name"),
        "frame_rate": _parse_rate(stream.get("avg_frame_rate")),
        "has_audio": first_stream(metadata, "audio") is not None,
    }


async def extract_audio(source: str | Path, destination: str | Path) -> Path:
    """Demux a mono 16 kHz WAV, the shape every speech model wants."""
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    args = [
        FFMPEG, "-hide_banner", "-nostdin", "-y", "-i", str(source),
        "-vn", "-ac", "1", "-ar", str(AUDIO_SAMPLE_RATE), "-f", "wav", str(target),
    ]
    await run_tool(args, timeout=DEMUX_TIMEOUT_SECONDS)
    if not target.exists() or target.stat().st_size == 0:
        raise MediaToolError("ffmpeg produced no audio output")
    return target


async def detect_scene_cuts(
    source: str | Path, *, threshold: float = SCENE_THRESHOLD
) -> list[float]:
    """Scene-cut timestamps via the ffmpeg ``select`` filter and ``showinfo``."""
    args = [
        FFMPEG, "-hide_banner", "-nostdin", "-i", str(source),
        "-filter:v", f"select='gt(scene,{threshold})',showinfo",
        "-an", "-f", "null", "-",
    ]
    _, stderr = await run_tool(args, timeout=SCENE_TIMEOUT_SECONDS)
    text = stderr.decode("utf-8", "replace")
    cuts = sorted({round(float(match), 3) for match in _PTS_TIME.findall(text)})
    return [cut for cut in cuts if cut > 0.0]


def scenes_from_cuts(cuts: list[float], duration: float) -> list[tuple[float, float]]:
    """Turn cut points into ``(start, end)`` spans, dropping micro-scenes.

    The floor adapts to the clip: a one-hour video should not be cut into
    half-second scenes, and a three-second clip must not collapse into one.
    """
    floor = _minimum_scene(duration)
    boundaries = [0.0, *[cut for cut in cuts if 0.0 < cut < duration], duration]
    spans: list[tuple[float, float]] = []
    for start, end in zip(boundaries, boundaries[1:], strict=False):
        if end - start < floor and spans:
            previous_start, _ = spans.pop()
            spans.append((previous_start, end))
            continue
        spans.append((start, end))
    return spans[:MAX_SCENES]


def _minimum_scene(duration: float) -> float:
    if duration <= 0:
        return MIN_SCENE_SECONDS
    return min(MIN_SCENE_SECONDS, max(duration / 4.0, MIN_SCENE_FLOOR_SECONDS))


def uniform_scenes(duration: float, interval: float = UNIFORM_SCENE_SECONDS) -> list[tuple[float, float]]:
    """Last-resort segmentation when no cut detector produced anything."""
    if duration <= 0:
        return []
    step = max(interval, MIN_SCENE_SECONDS)
    spans: list[tuple[float, float]] = []
    start = 0.0
    while start < duration and len(spans) < MAX_SCENES:
        spans.append((round(start, 3), round(min(start + step, duration), 3)))
        start += step
    return spans


async def extract_frame(source: str | Path, timestamp: float) -> bytes:
    """Single JPEG keyframe at ``timestamp`` (fast seek, then one frame)."""
    with tempfile.TemporaryDirectory(prefix="spectra-frame-") as workdir:
        target = Path(workdir) / "frame.jpg"
        args = [
            FFMPEG, "-hide_banner", "-nostdin", "-y",
            "-ss", f"{max(timestamp, 0.0):.3f}", "-i", str(source),
            "-frames:v", "1", "-q:v", "2", str(target),
        ]
        await run_tool(args, timeout=FRAME_TIMEOUT_SECONDS)
        if not target.exists() or target.stat().st_size == 0:
            raise MediaToolError(f"no frame decoded at {timestamp:.3f}s")
        return target.read_bytes()


def _as_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _parse_rate(value: Any) -> float | None:
    if not value or "/" not in str(value):
        return _as_float(value)
    numerator, _, denominator = str(value).partition("/")
    try:
        denominator_value = float(denominator)
        return round(float(numerator) / denominator_value, 3) if denominator_value else None
    except ValueError:
        return None
