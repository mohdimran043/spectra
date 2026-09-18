"""Semantic chunking.

Blocks are packed into retrievable windows in three passes:

1. **Structure first** - section/heading boundaries split the stream, and a
   table is always a chunk of its own.
2. **Sentence granularity** - windows are filled with whole sentences, so a
   chunk is never cut mid-sentence unless a single sentence is itself larger
   than the target.
3. **Overlap** - each window re-opens with the trailing ~15% of the previous
   one so a fact that straddles a boundary is still retrievable.

Every draft keeps the page / section / ordinal / bbox of its FIRST contributing
block, which is what makes a citation point at an exact place in the source.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Final, Protocol

from .extractors.base import STANDALONE_KINDS, BBox, ExtractedBlock

DEFAULT_TARGET_TOKENS: Final[int] = 380
DEFAULT_OVERLAP_RATIO: Final[float] = 0.15
MIN_WINDOW_TOKENS: Final[int] = 4
#: Kinds whose text must stay verbatim instead of being split into sentences.
ATOMIC_KINDS: Final[frozenset[str]] = frozenset({"table", "code"})
SPEAKER_BREAK_FRACTION: Final[float] = 0.34

_SENTENCE_SPLIT: Final[re.Pattern[str]] = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass(frozen=True)
class ChunkDraft:
    """A packed window of blocks, ready to become a ``Chunk``."""

    text: str
    ordinal: int
    kind: str = "paragraph"
    page: int | None = None
    section: str | None = None
    bbox: BBox | None = None
    token_count: int = 0
    block_ordinals: tuple[int, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TranscriptWindow:
    """Adjacent transcript segments merged into one retrievable span."""

    text: str
    ordinal: int
    start_seconds: float
    end_seconds: float
    speakers: tuple[str, ...] = ()
    segment_count: int = 0
    token_count: int = 0


class TimedSegment(Protocol):
    """Anything with a start, an end and some text (e.g. ``TranscriptSegment``)."""

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class _Unit:
    text: str
    tokens: int
    block: ExtractedBlock
    index: int


def count_tokens(text: str) -> int:
    """Whitespace token approximation - deliberately cheap and deterministic."""
    return len(text.split())


def split_sentences(text: str) -> list[str]:
    """Split on sentence terminators and newlines, keeping non-empty fragments."""
    return [part.strip() for part in _SENTENCE_SPLIT.split(text) if part.strip()]


def chunk_blocks(
    blocks: Sequence[ExtractedBlock],
    *,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    overlap_ratio: float = DEFAULT_OVERLAP_RATIO,
) -> list[ChunkDraft]:
    """Pack extracted blocks into semantic chunks (pure function, no I/O)."""
    if target_tokens <= 0:
        raise ValueError("target_tokens must be positive")
    if not 0.0 <= overlap_ratio < 1.0:
        raise ValueError("overlap_ratio must be in [0, 1)")

    drafts: list[ChunkDraft] = []
    for group in _group_blocks(blocks):
        if group and group[0].kind in STANDALONE_KINDS:
            drafts.extend(_atomic_drafts(group[0], target_tokens))
            continue
        drafts.extend(_pack_group(group, target_tokens, overlap_ratio))
    return [replace(draft, ordinal=index) for index, draft in enumerate(drafts)]


# ---------------------------------------------------------------------------
# Transcript quality.  Speech recognition invents text on silence and music:
# "Thank you for watching!", "Oh", "© transcript <name>".  Indexed, these become
# searchable content - 9 of 122 chunks on the demo corpus - and they surface for
# any query with nothing better to match.  They are dropped at ingestion, where
# the cost is paid once, rather than filtered at query time.
# ---------------------------------------------------------------------------

#: A transcript window shorter than this carries no retrievable content.
#: "Oh" and "you" are the two most common ASR hallucinations on silence.
MIN_TRANSCRIPT_CHARS: Final[int] = 8

#: Whole-utterance hallucinations, matched against the de-duplicated text so
#: "Thank you. Thank you." is caught by the single phrase.
HALLUCINATED_UTTERANCES: Final[frozenset[str]] = frozenset(
    {
        "thank you", "thanks", "thank you very much", "thank you so much",
        "thank you for watching", "thanks for watching", "thank you for listening",
        "please subscribe", "like and subscribe", "subscribe to my channel",
        "bye", "goodbye", "bye bye", "you", "oh", "hmm", "mm", "uh", "um",
        "music", "applause", "silence", "laughter", "foreign",
    }
)

#: Credit lines the model copies from its training data rather than the audio.
CREDIT_PREFIXES: Final[tuple[str, ...]] = (
    "transcript", "subtitles", "subs by", "captions", "translated by",
    "transcription by", "amara.org", "www.",
)

_PUNCTUATION = re.compile(r"[^\w\s]+")
_WHITESPACE = re.compile(r"\s+")


def _normalise_utterance(text: str) -> str:
    """Lower-cased words only - punctuation and symbols carry no speech."""
    return _WHITESPACE.sub(" ", _PUNCTUATION.sub(" ", text.lower())).strip()


def _collapse_repeats(text: str) -> str:
    """"thank you thank you thank you" -> "thank you".

    Looping on one phrase is the signature of a model decoding silence, so the
    repetition is removed before the text is matched rather than being treated
    as length.
    """
    words = text.split()
    for size in range(1, len(words) // 2 + 1):
        if len(words) % size:
            continue
        head = words[:size]
        if all(words[i : i + size] == head for i in range(0, len(words), size)):
            return " ".join(head)
    return text


def is_hallucinated_transcript(text: str) -> bool:
    """True when a transcript window is recognition noise rather than speech."""
    normalised = _normalise_utterance(text)
    if not normalised:
        return True
    collapsed = _collapse_repeats(normalised)
    if collapsed in HALLUCINATED_UTTERANCES:
        return True
    if collapsed.startswith(CREDIT_PREFIXES):
        return True
    return len(collapsed) < MIN_TRANSCRIPT_CHARS


def drop_hallucinated(windows: Sequence[TranscriptWindow]) -> list[TranscriptWindow]:
    """``windows`` with the recognition noise removed, ordinals left intact."""
    return [window for window in windows if not is_hallucinated_transcript(window.text)]


def merge_transcript_segments(
    segments: Sequence[TimedSegment],
    *,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
) -> list[TranscriptWindow]:
    """Merge adjacent timed segments up to ``target_tokens``, keeping the span."""
    windows: list[TranscriptWindow] = []
    buffer: list[TimedSegment] = []
    tokens = 0
    for segment in segments:
        text = str(getattr(segment, "text", "") or "").strip()
        if not text:
            continue
        segment_tokens = count_tokens(text)
        if buffer and _should_break(buffer, segment, tokens, segment_tokens, target_tokens):
            windows.append(_window(buffer, len(windows)))
            buffer, tokens = [], 0
        buffer.append(segment)
        tokens += segment_tokens
    if buffer:
        windows.append(_window(buffer, len(windows)))
    return windows


def window_text(windows: Sequence[TranscriptWindow], start: float, end: float) -> str:
    """Transcript text overlapping ``[start, end)`` - used for video scene chunks."""
    parts = [w.text for w in windows if w.end_seconds > start and w.start_seconds < end]
    return " ".join(part.strip() for part in parts if part.strip()).strip()


def _should_break(
    buffer: Sequence[TimedSegment],
    segment: TimedSegment,
    tokens: int,
    segment_tokens: int,
    target_tokens: int,
) -> bool:
    if tokens + segment_tokens > target_tokens:
        return True
    previous = getattr(buffer[-1], "speaker", None)
    current = getattr(segment, "speaker", None)
    if previous and current and previous != current:
        return tokens >= target_tokens * SPEAKER_BREAK_FRACTION
    return False


def _window(buffer: Sequence[TimedSegment], ordinal: int) -> TranscriptWindow:
    text = " ".join(str(segment.text).strip() for segment in buffer).strip()
    speakers = tuple(
        dict.fromkeys(str(getattr(s, "speaker", "") or "") for s in buffer if getattr(s, "speaker", None))
    )
    return TranscriptWindow(
        text=text,
        ordinal=ordinal,
        start_seconds=float(buffer[0].start),
        end_seconds=float(buffer[-1].end),
        speakers=speakers,
        segment_count=len(buffer),
        token_count=count_tokens(text),
    )


def _group_blocks(blocks: Sequence[ExtractedBlock]) -> list[list[ExtractedBlock]]:
    """Split the block stream on headings, sections and standalone kinds."""
    groups: list[list[ExtractedBlock]] = []
    current: list[ExtractedBlock] = []
    for block in blocks:
        if not block.text.strip():
            continue
        if block.kind in STANDALONE_KINDS:
            if current:
                groups.append(current)
                current = []
            groups.append([block])
            continue
        if current and _starts_group(block, current[-1]):
            groups.append(current)
            current = []
        current.append(block)
    if current:
        groups.append(current)
    return groups


def _starts_group(block: ExtractedBlock, previous: ExtractedBlock) -> bool:
    return block.kind == "heading" or block.section != previous.section


def _atomic_drafts(block: ExtractedBlock, target_tokens: int) -> list[ChunkDraft]:
    """A table (or other atomic block) becomes its own chunk, split only if huge."""
    tokens = count_tokens(block.text)
    if tokens <= target_tokens * 2:
        return [_draft_from(block.text, [block], tokens, ordinal=0)]
    lines = block.text.splitlines()
    header = lines[:2] if len(lines) > 2 and lines[1].strip().startswith("|") else []
    body = lines[len(header) :]
    drafts: list[ChunkDraft] = []
    window: list[str] = []
    for line in body:
        window.append(line)
        if count_tokens("\n".join(header + window)) >= target_tokens:
            drafts.append(_draft_from("\n".join(header + window), [block], 0, ordinal=len(drafts)))
            window = []
    if window:
        drafts.append(_draft_from("\n".join(header + window), [block], 0, ordinal=len(drafts)))
    return drafts


def _pack_group(
    blocks: Sequence[ExtractedBlock], target_tokens: int, overlap_ratio: float
) -> list[ChunkDraft]:
    units = _units(blocks, target_tokens)
    if not units:
        return []

    drafts: list[ChunkDraft] = []
    window: list[_Unit] = []
    tokens = 0
    carried = 0
    for unit in units:
        if window and tokens + unit.tokens > target_tokens:
            drafts.append(_draft_from_units(window, len(drafts)))
            window = _overlap_tail(window, int(target_tokens * overlap_ratio))
            carried = len(window)
            tokens = sum(item.tokens for item in window)
        window.append(unit)
        tokens += unit.tokens
    if window and len(window) > carried:
        drafts.append(_draft_from_units(window, len(drafts)))
    return drafts


def _units(blocks: Sequence[ExtractedBlock], target_tokens: int) -> list[_Unit]:
    units: list[_Unit] = []
    for block in blocks:
        pieces = [block.text] if block.kind in ATOMIC_KINDS else split_sentences(block.text)
        for piece in pieces:
            for fragment in _fit(piece, target_tokens):
                units.append(_Unit(text=fragment, tokens=count_tokens(fragment), block=block, index=len(units)))
    return units


def _fit(text: str, target_tokens: int) -> list[str]:
    """Hard-split only when a single sentence cannot fit a window."""
    words = text.split()
    if len(words) <= target_tokens:
        return [text]
    return [" ".join(words[start : start + target_tokens]) for start in range(0, len(words), target_tokens)]


def _overlap_tail(window: Sequence[_Unit], budget_tokens: int) -> list[_Unit]:
    """Trailing whole sentences of a window, up to the overlap budget."""
    if budget_tokens <= 0 or len(window) < 2:
        return []
    tail: list[_Unit] = []
    total = 0
    for unit in reversed(window[1:]):
        if total + unit.tokens > budget_tokens:
            break
        tail.insert(0, unit)
        total += unit.tokens
    return tail


def _draft_from_units(window: Sequence[_Unit], ordinal: int) -> ChunkDraft:
    parts: list[str] = []
    previous_block: ExtractedBlock | None = None
    for unit in window:
        separator = "" if previous_block is None else ("\n" if unit.block is not previous_block else " ")
        parts.append(separator + unit.text)
        previous_block = unit.block
    text = "".join(parts).strip()
    blocks = [u.block for i, u in enumerate(window) if i == 0 or u.block is not window[i - 1].block]
    return _draft_from(text, blocks, count_tokens(text), ordinal=ordinal)


def _draft_from(
    text: str, blocks: Sequence[ExtractedBlock], tokens: int, *, ordinal: int
) -> ChunkDraft:
    first = blocks[0]
    return ChunkDraft(
        text=text,
        ordinal=ordinal,
        kind=first.kind,
        page=first.page,
        section=first.section,
        bbox=first.bbox,
        token_count=tokens or count_tokens(text),
        block_ordinals=tuple(block.ordinal for block in blocks),
        metadata=dict(first.metadata),
    )
