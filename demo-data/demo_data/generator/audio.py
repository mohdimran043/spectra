"""The three generated conversations.

Content lives in the transcripts; the WAV beside each transcript is a
speech-shaped placeholder (see :mod:`.speech`).  Each clip records the second
range that answers its benchmark question, so "find where the speaker
discusses the architecture change" has a checkable ground truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from spectra_config.logging import get_logger

from .constants import AUDIO_DIR
from .rng import clock
from .speech import (
    MEDIA_TYPE_WAV,
    TRANSCRIPT_SUFFIX,
    Segment,
    find_span,
    layout_segments,
    transcript_text,
    write_transcript,
    write_wav,
)
from .story import AUTH_SERVICE, FRAUD_SERVICE, GATEWAY_SERVICE, SESSION_DB
from .world import World

log = get_logger(__name__)

ARCHITECTURE_CUE: Final[str] = "sharding"
ROOT_CAUSE_CUE: Final[str] = "token validation"
AUTH_CUE: Final[str] = "authentication service"


@dataclass(frozen=True)
class AudioArtifact:
    audio_id: str
    slug: str
    path: str
    transcript_path: str
    media_type: str
    title: str
    duration_seconds: float
    speakers: tuple[str, ...]
    entities: tuple[str, ...]
    tags: tuple[str, ...]
    answer_spans: dict[str, tuple[float, float]]
    text: str
    size_bytes: int


def _standup_turns(world: World) -> tuple[tuple[str, str], ...]:
    cast = world.cast
    return (
        (cast.commander.speaker, "Good morning. One item before we start: yesterday's payment failures."),
        (cast.auth_engineer.speaker,
         f"The authentication service is the thing that broke. Token validation went from two hundred "
         f"milliseconds to over eight seconds after release {cast.release_tag}."),
        (cast.payments_engineer.speaker,
         f"On our side {GATEWAY_SERVICE} just sat there waiting. The pool filled up and we started "
         f"rejecting authorisations."),
        (cast.auth_engineer.speaker,
         f"Right. It is not a {GATEWAY_SERVICE} bug. The {AUTH_SERVICE} timeout is the root cause and "
         f"{world.incident_id} says so."),
        (cast.fraud_analyst.speaker,
         f"I checked the fraud angle. The velocity rule blocked nine payments, but not "
         f"{world.variant('transaction', 1)}."),
        (cast.commander.speaker,
         f"So the merchant ticket for {world.variant('transaction', 3)} closes as platform incident, "
         f"not fraud."),
        (cast.reliability_engineer.speaker,
         "I will keep watching the authorisation success rate for another day."),
    )


def _bridge_turns(world: World) -> tuple[tuple[str, str], ...]:
    cast, timeline = world.cast, world.cast.timeline
    return (
        (cast.commander.speaker,
         f"Incident bridge for {world.incident_id}, opened {clock(timeline.incident_opened_at)} UTC. "
         f"Who has the merchant reference?"),
        (cast.payments_engineer.speaker,
         f"The merchant quoted {world.variant('transaction', 2)}. Customer is "
         f"{world.variant('customer', 1)}."),
        (cast.fraud_analyst.speaker,
         f"First theory is the fraud rule we shipped last night. {FRAUD_SERVICE} is the obvious suspect."),
        (cast.reliability_engineer.speaker,
         "Second theory is the transit packet loss, but that was three days ago and the counters are "
         "clean tonight."),
        (cast.payments_engineer.speaker,
         "Third theory from support is an insufficient balance. The account has eighteen thousand "
         "available, so that is not it."),
        (cast.auth_engineer.speaker,
         f"I have the answer. Token validation p99 is eight point four seconds on {AUTH_SERVICE}. "
         f"{GATEWAY_SERVICE} blocks on that call, so the pool is exhausted."),
        (cast.commander.speaker,
         f"Then we roll back release {cast.release_tag}. I want the change board on the record."),
        (cast.approver.speaker,
         f"Board approves the emergency rollback out of band at {clock(timeline.approval_at)} UTC."),
    )


def _architecture_turns(world: World) -> tuple[tuple[str, str], ...]:
    cast = world.cast
    return (
        (cast.data_architect.speaker, "Architecture review. One agenda item, the session store."),
        (cast.auth_engineer.speaker,
         f"{AUTH_SERVICE} contends on a single {SESSION_DB} primary on every token validation."),
        (cast.data_architect.speaker,
         f"The architecture change I am proposing is sharding: split {SESSION_DB} into three database "
         f"nodes keyed by tenant band, each with its own replica."),
        (cast.reliability_engineer.speaker,
         "Cross-shard lookups add a hop. We still need the revocation list cached regardless."),
        (cast.data_architect.speaker,
         "Agreed. Sharding removes the write hotspot; the cache fixes the latency we saw in the incident."),
        (cast.commander.speaker, "Approved in principle. Write the decision record."),
    )


def _write_clip(
    world: World,
    slug: str,
    title: str,
    turns: tuple[tuple[str, str], ...],
    cue: str,
    tags: tuple[str, ...],
    entities: tuple[str, ...],
    directory: Path,
    out_dir: Path,
) -> AudioArtifact:
    audio_id = world.ids.audio()
    segments: tuple[Segment, ...] = layout_segments(turns)
    path = directory / f"{slug}.wav"
    duration = write_wav(path, segments)
    transcript_path = directory / f"{slug}{TRANSCRIPT_SUFFIX}"
    write_transcript(transcript_path, audio_id, segments, source="generated-ground-truth")
    span = find_span(segments, cue)
    return AudioArtifact(
        audio_id=audio_id,
        slug=slug,
        path=path.relative_to(out_dir).as_posix(),
        transcript_path=transcript_path.relative_to(out_dir).as_posix(),
        media_type=MEDIA_TYPE_WAV,
        title=title,
        duration_seconds=duration,
        speakers=tuple(dict.fromkeys(segment.speaker for segment in segments)),
        entities=entities,
        tags=tags,
        answer_spans={cue: span} if span else {},
        text=transcript_text(segments),
        size_bytes=path.stat().st_size,
    )


def generate_audio(world: World, out_dir: Path) -> tuple[AudioArtifact, ...]:
    """Write the standup, the incident bridge and the architecture review."""
    directory = out_dir / AUDIO_DIR
    directory.mkdir(parents=True, exist_ok=True)
    clips = (
        _write_clip(
            world, "standup-engineering", "Engineering standup", _standup_turns(world), AUTH_CUE,
            ("standup", "auth"), (world.incident_id, world.transaction_id), directory, out_dir,
        ),
        _write_clip(
            world, "incident-bridge-call", "Incident bridge call", _bridge_turns(world), ROOT_CAUSE_CUE,
            ("bridge", "incident", "candidate explanations"),
            (world.incident_id, world.transaction_id, world.customer_id), directory, out_dir,
        ),
        _write_clip(
            world, "architecture-review-call", "Architecture review", _architecture_turns(world),
            ARCHITECTURE_CUE, ("architecture", "sharding"), (SESSION_DB, AUTH_SERVICE), directory, out_dir,
        ),
    )
    log.info("demo_data.audio_generated", count=len(clips), directory=str(directory))
    return clips
