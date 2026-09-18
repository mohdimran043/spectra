"""Real MP4s built from generated slides and the matching placeholder audio.

Every scene is a distinct rendered frame, so scene detection has genuine cuts
to find, and the ground-truth scene boundaries are written next to the file.
At least one video shows a transaction id on screen (the video to OCR to
database path) and one discusses the architecture change at a recorded second.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final, Sequence

from spectra_config.logging import get_logger

from .canvas import ACCENT, BODY_SIZE, DANGER, MUTED, SMALL_SIZE, TITLE_SIZE, Sheet
from .constants import (
    FFMPEG_TIMEOUT_SECONDS,
    FILLER_VIDEO_SCENE_SECONDS,
    INTER_SEGMENT_SILENCE_SECONDS,
    VIDEO_AUDIO_BITRATE,
    VIDEO_CRF,
    VIDEO_FPS,
    VIDEO_HEIGHT,
    VIDEO_PRESET,
    VIDEO_WIDTH,
    VIDEOS_DIR,
)
from .speech import TRANSCRIPT_SUFFIX, Segment, layout_segments, transcript_text, write_transcript, write_wav
from .videoscripts import VideoScript, build_video_scripts, filler_script
from .world import World

log = get_logger(__name__)

MEDIA_TYPE_MP4: Final[str] = "video/mp4"
SCENES_SUFFIX: Final[str] = ".scenes.json"
FFMPEG_BINARY: Final[str] = "ffmpeg"


class VideoEncodeError(RuntimeError):
    """Raised when ffmpeg refuses to produce the clip."""


@dataclass(frozen=True)
class SceneBoundary:
    index: int
    start: float
    end: float
    title: str
    text: str


@dataclass(frozen=True)
class VideoArtifact:
    video_id: str
    slug: str
    path: str
    transcript_path: str
    scenes_path: str
    media_type: str
    title: str
    duration_seconds: float
    scenes: tuple[SceneBoundary, ...]
    answer_spans: dict[str, tuple[float, float]]
    entities: tuple[str, ...]
    tags: tuple[str, ...]
    text: str
    size_bytes: int


def _render_slide(script: VideoScript, index: int, path: Path, video_id: str) -> str:
    scene = script.scenes[index]
    sheet = Sheet(VIDEO_WIDTH, VIDEO_HEIGHT)
    sheet.panel((0, 0, VIDEO_WIDTH, 96))
    sheet.text((48, 28), scene.title, size=TITLE_SIZE, bold=True, role="title")
    for line_index, line in enumerate(scene.lines):
        colour = DANGER if line.startswith("!") else MUTED if line.startswith("-") else ACCENT
        sheet.text((48, 160 + line_index * 56), line.lstrip("!- "), size=BODY_SIZE, colour=colour, role="slide")
    sheet.text((48, VIDEO_HEIGHT - 60), f"Video {video_id} | scene {index + 1} of {len(script.scenes)}",
               size=SMALL_SIZE, colour=MUTED, role="watermark")
    sheet.save(path)
    return "\n".join(drawn.text for drawn in sheet.drawn)


def _boundaries(script: VideoScript, segments: Sequence[Segment]) -> tuple[tuple[float, float], ...]:
    spans: list[tuple[float, float]] = []
    cursor = 0.0
    position = 0
    for scene in script.scenes:
        group = segments[position : position + len(scene.turns)]
        position += len(scene.turns)
        end = (group[-1].end + INTER_SEGMENT_SILENCE_SECONDS) if group else cursor + FILLER_VIDEO_SCENE_SECONDS
        spans.append((round(cursor, 3), round(end, 3)))
        cursor = end
    return tuple(spans)


def _encode(frames: Sequence[Path], durations: Sequence[float], audio: Path, target: Path,
            workdir: Path) -> None:
    listing = workdir / "frames.txt"
    lines: list[str] = []
    for frame, duration in zip(frames, durations):
        lines.append(f"file '{frame.as_posix()}'")
        lines.append(f"duration {duration:.3f}")
    lines.append(f"file '{frames[-1].as_posix()}'")
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    command = [
        FFMPEG_BINARY, "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(listing),
        "-i", str(audio),
        "-c:v", "libx264", "-preset", VIDEO_PRESET, "-crf", str(VIDEO_CRF),
        "-pix_fmt", "yuv420p", "-r", str(VIDEO_FPS),
        "-c:a", "aac", "-b:a", VIDEO_AUDIO_BITRATE, "-shortest", str(target),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT_SECONDS)
    except FileNotFoundError as exc:
        raise VideoEncodeError(f"{FFMPEG_BINARY} is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise VideoEncodeError(f"ffmpeg timed out after {FFMPEG_TIMEOUT_SECONDS}s") from exc
    if result.returncode != 0 or not target.exists():
        raise VideoEncodeError(f"ffmpeg failed for {target.name}: {result.stderr.strip()[:400]}")


def _build(script: VideoScript, world: World, directory: Path, out_dir: Path) -> VideoArtifact:
    video_id = world.ids.video()
    turns = tuple(turn for scene in script.scenes for turn in scene.turns)
    segments = layout_segments(turns)
    spans = _boundaries(script, segments)
    total = spans[-1][1] if spans else FILLER_VIDEO_SCENE_SECONDS
    target = directory / f"{script.slug}.mp4"
    with TemporaryDirectory(prefix="spectra-video-") as raw:
        workdir = Path(raw)
        frames: list[Path] = []
        texts: list[str] = []
        for index in range(len(script.scenes)):
            frame = workdir / f"scene_{index:03d}.png"
            texts.append(_render_slide(script, index, frame, video_id))
            frames.append(frame)
        audio_path = workdir / "track.wav"
        write_wav(audio_path, segments, total_seconds=total)
        _encode(frames, [end - start for start, end in spans], audio_path, target, workdir)

    scenes = tuple(
        SceneBoundary(index=index, start=spans[index][0], end=spans[index][1],
                      title=script.scenes[index].title, text=texts[index])
        for index in range(len(script.scenes))
    )
    transcript_path = directory / f"{script.slug}{TRANSCRIPT_SUFFIX}"
    write_transcript(transcript_path, video_id, segments, source="generated-ground-truth")
    scenes_path = directory / f"{script.slug}{SCENES_SUFFIX}"
    scenes_path.write_text(
        json.dumps(
            {
                "video_id": video_id,
                "is_ground_truth": True,
                "scenes": [
                    {"index": scene.index, "start": scene.start, "end": scene.end,
                     "title": scene.title, "text": scene.text}
                    for scene in scenes
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    answer_spans = {
        cue: (scenes[index].start, scenes[index].end) for cue, index in script.answer_scenes.items()
    }
    return VideoArtifact(
        video_id=video_id,
        slug=script.slug,
        path=target.relative_to(out_dir).as_posix(),
        transcript_path=transcript_path.relative_to(out_dir).as_posix(),
        scenes_path=scenes_path.relative_to(out_dir).as_posix(),
        media_type=MEDIA_TYPE_MP4,
        title=script.title,
        duration_seconds=round(total, 3),
        scenes=scenes,
        answer_spans=answer_spans,
        entities=script.entities,
        tags=script.tags,
        text=transcript_text(segments) + "\n" + "\n".join(texts),
        size_bytes=target.stat().st_size,
    )


def generate_videos(world: World, out_dir: Path) -> tuple[VideoArtifact, ...]:
    """Encode the narrative videos, then cheap filler clips up to the tier size."""
    directory = out_dir / VIDEOS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    scripts = list(build_video_scripts(world))
    for index in range(max(0, world.scale.videos - len(scripts))):
        scripts.append(filler_script(world, index))
    artifacts = tuple(_build(script, world, directory, out_dir) for script in scripts)
    log.info("demo_data.videos_generated", count=len(artifacts), directory=str(directory))
    return artifacts
