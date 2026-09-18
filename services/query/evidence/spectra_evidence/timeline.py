"""Cross-modal timeline construction.

A timeline has to place a database row, a document date, a video offset and an
image EXIF stamp on one axis.  Timestamps are normalised, never invented: when
only a media offset is known and the recording start is not, the event is marked
``relative`` instead of being given a fake wall-clock time.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone

from spectra_config.logging import get_logger
from spectra_schemas import CanonicalEntity, EvidenceItem, TimelineEvent, format_timestamp

from .locators import asset_key, media_offset_seconds
from .text_utils import normalise_whitespace, truncate

log = get_logger(__name__)

# Two sources describing the same logged action rarely disagree by more than a
# minute, so identical labels inside this window are one event, not two.
DEFAULT_DEDUPE_WINDOW_SECONDS = 60.0
# Default half-width when the caller asks for "what happened around X".
DEFAULT_WINDOW = timedelta(minutes=15)
# Timeline labels are rendered in a narrow column.
MAX_LABEL_CHARS = 80
MAX_DETAIL_CHARS = 240
# Relative (offset-only) events are anchored at the Unix epoch so the offset is
# preserved exactly and they are visibly separate from wall-clock events.
RELATIVE_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

PRECISION_EXACT = "exact"
PRECISION_MINUTE = "minute"
PRECISION_DAY = "day"
PRECISION_RELATIVE = "relative"
# Ordering used when two events share a timestamp: the more precise one wins.
_PRECISION_RANK: Mapping[str, int] = {
    PRECISION_EXACT: 0,
    PRECISION_MINUTE: 1,
    PRECISION_DAY: 2,
    PRECISION_RELATIVE: 3,
}

# "Which document is the latest approved version": approved/final outrank the
# merely current copy, and a superseded version can never win.
VERSION_STATUS_RANK: Mapping[str, int] = {
    "approved": 4,
    "final": 4,
    "current": 3,
    "unknown": 2,
    "draft": 1,
    "superseded": 0,
}


class TimelineBuilder:
    """Builds, deduplicates and renders chronological views of evidence."""

    def __init__(self, *, dedupe_window_seconds: float = DEFAULT_DEDUPE_WINDOW_SECONDS) -> None:
        self._window = max(float(dedupe_window_seconds), 0.0)

    def build(
        self,
        evidence: Sequence[EvidenceItem],
        entities: Sequence[CanonicalEntity] = (),
        extra_events: Sequence[TimelineEvent] = (),
        *,
        asset_starts: Mapping[str, datetime] | None = None,
    ) -> list[TimelineEvent]:
        """Normalise evidence into sorted, deduplicated timeline events."""
        entity_ids = [entity.entity_id for entity in entities]
        events: list[TimelineEvent] = list(extra_events)
        for item in evidence:
            resolved = _timestamp_for(item, asset_starts or {})
            if resolved is None:
                log.debug("timeline.undated_evidence_skipped", evidence_id=item.evidence_id)
                continue
            occurred_at, precision = resolved
            events.append(_event_from(item, occurred_at, precision, entity_ids))
        ordered = sorted(events, key=_sort_key)
        return self._deduplicate(ordered)

    def _deduplicate(self, ordered: Sequence[TimelineEvent]) -> list[TimelineEvent]:
        kept: list[TimelineEvent] = []
        for event in ordered:
            index = _near_duplicate_index(kept, event, self._window)
            if index is None:
                kept.append(event)
                continue
            kept[index] = _merge_events(kept[index], event)
        dropped = len(ordered) - len(kept)
        if dropped:
            log.debug("timeline.deduplicated", dropped=dropped, window_seconds=self._window)
        return kept

    # -- queries ----------------------------------------------------------
    @staticmethod
    def window(
        events: Sequence[TimelineEvent],
        around: datetime,
        before: timedelta = DEFAULT_WINDOW,
        after: timedelta = DEFAULT_WINDOW,
    ) -> list[TimelineEvent]:
        """Events falling in ``[around - before, around + after]``."""
        centre = _as_utc(around)
        low, high = centre - abs(before), centre + abs(after)
        return [event for event in events if low <= _as_utc(event.occurred_at) <= high]

    @staticmethod
    def describe(events: Sequence[TimelineEvent]) -> list[str]:
        """Render as ``10:42:01  Transaction created``.

        Times alone are ambiguous once a timeline spans more than one day, so
        the date is prefixed only when it is actually needed.
        """
        days = {
            _as_utc(event.occurred_at).date()
            for event in events
            if event.precision != PRECISION_RELATIVE
        }
        with_date = len(days) > 1
        return [f"{_render_time(event, with_date=with_date)}  {event.label}" for event in events]

    @staticmethod
    def latest_version_of(items: Sequence[EvidenceItem]) -> EvidenceItem | None:
        """The latest approved version among competing document versions."""
        if not items:
            return None
        return max(items, key=_version_key)


def _version_key(item: EvidenceItem) -> tuple[int, tuple[int, ...], float, str]:
    provenance = item.provenance
    status = (provenance.version_status or "unknown").strip().lower()
    rank = VERSION_STATUS_RANK.get(status, VERSION_STATUS_RANK["unknown"])
    stamp = provenance.modified_at or provenance.created_at
    modified = _as_utc(stamp).timestamp() if stamp else 0.0
    return rank, _version_tuple(provenance.version), modified, item.evidence_id


def _version_tuple(version: str | None) -> tuple[int, ...]:
    if not version:
        return (0,)
    parts = [part for part in "".join(c if c.isdigit() else "." for c in version).split(".") if part]
    return tuple(int(part) for part in parts) or (0,)


def _timestamp_for(
    item: EvidenceItem, asset_starts: Mapping[str, datetime]
) -> tuple[datetime, str] | None:
    """Best wall-clock (or relative) time for this evidence, or None."""
    if item.occurred_at is not None:
        stamp = _as_utc(item.occurred_at)
        return stamp, _precision_of(stamp)
    offset = media_offset_seconds(item.provenance)
    if offset is not None:
        anchor = asset_starts.get(asset_key(item.provenance)) or item.provenance.created_at
        if anchor is not None:
            return _as_utc(anchor) + timedelta(seconds=float(offset)), PRECISION_EXACT
        return RELATIVE_EPOCH + timedelta(seconds=float(offset)), PRECISION_RELATIVE
    for candidate in (item.provenance.created_at, item.provenance.modified_at):
        if candidate is not None:
            stamp = _as_utc(candidate)
            return stamp, _precision_of(stamp)
    return None


def _precision_of(stamp: datetime) -> str:
    if stamp.second or stamp.microsecond:
        return PRECISION_EXACT
    if stamp.hour or stamp.minute:
        return PRECISION_MINUTE
    return PRECISION_DAY


def _event_from(
    item: EvidenceItem, occurred_at: datetime, precision: str, entity_ids: Sequence[str]
) -> TimelineEvent:
    label = _label_from(item.summary) or item.citation()
    digest = hashlib.sha256(
        "\x1f".join([label.lower(), occurred_at.isoformat(), item.evidence_id]).encode("utf-8")
    ).hexdigest()[:12]
    entities = [entity for entity in {*item.entities, *entity_ids} if entity]
    return TimelineEvent(
        event_id=f"evt_{digest}",
        occurred_at=occurred_at,
        label=label,
        detail=truncate(f"{item.summary} ({item.citation()})", MAX_DETAIL_CHARS),
        modality=item.modality,
        evidence_ids=[item.evidence_id],
        entity_ids=sorted(entities),
        source_id=item.provenance.source_id,
        precision=precision,
    )


def _label_from(summary: str) -> str:
    cleaned = normalise_whitespace(summary)
    for separator in (";", " - ", ". "):
        head, found, _ = cleaned.partition(separator)
        if found:
            cleaned = head
            break
    return truncate(cleaned.rstrip("."), MAX_LABEL_CHARS)


def _sort_key(event: TimelineEvent) -> tuple[datetime, int, str]:
    return (_as_utc(event.occurred_at), _PRECISION_RANK.get(event.precision, 9), event.event_id)


def _near_duplicate_index(
    kept: Sequence[TimelineEvent], event: TimelineEvent, window_seconds: float
) -> int | None:
    label = event.label.strip().lower()
    for index, candidate in enumerate(kept):
        if candidate.label.strip().lower() != label:
            continue
        delta = abs((_as_utc(candidate.occurred_at) - _as_utc(event.occurred_at)).total_seconds())
        if delta <= window_seconds:
            return index
    return None


def _merge_events(kept: TimelineEvent, other: TimelineEvent) -> TimelineEvent:
    """Merge two observations of the same event into a NEW event."""
    better_precision = min(
        (kept.precision, other.precision), key=lambda value: _PRECISION_RANK.get(value, 9)
    )
    return kept.model_copy(
        update={
            "evidence_ids": sorted({*kept.evidence_ids, *other.evidence_ids}),
            "entity_ids": sorted({*kept.entity_ids, *other.entity_ids}),
            "precision": better_precision,
            "detail": kept.detail or other.detail,
        }
    )


def _render_time(event: TimelineEvent, *, with_date: bool = False) -> str:
    stamp = _as_utc(event.occurred_at)
    if event.precision == PRECISION_RELATIVE:
        return f"+{format_timestamp((stamp - RELATIVE_EPOCH).total_seconds())}"
    if event.precision == PRECISION_DAY:
        return stamp.strftime("%Y-%m-%d")
    return stamp.strftime("%Y-%m-%d %H:%M:%S" if with_date else "%H:%M:%S")


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


__all__ = [
    "DEFAULT_DEDUPE_WINDOW_SECONDS",
    "PRECISION_DAY",
    "PRECISION_EXACT",
    "PRECISION_MINUTE",
    "PRECISION_RELATIVE",
    "RELATIVE_EPOCH",
    "VERSION_STATUS_RANK",
    "TimelineBuilder",
]
