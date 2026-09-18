"""Seeded identifier and value generation.

Every id in the dataset comes from here, in the documented enterprise formats,
and every chosen id is written into the manifest.  No downstream module - and
no benchmark question - may contain a literal demo id: they all read it back
from the manifest, which is what makes the narrative survive a re-seed.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TypeVar

from .constants import (
    ASSET_DIGITS,
    ASSET_PREFIX,
    AUDIO_DIGITS,
    AUDIO_PREFIX,
    CUSTOMER_DIGITS,
    CUSTOMER_PREFIX,
    DOCUMENT_DIGITS,
    DOCUMENT_PREFIX,
    IMAGE_DIGITS,
    IMAGE_PREFIX,
    INCIDENT_DIGITS,
    INCIDENT_PREFIX,
    TRANSACTION_DIGITS,
    TRANSACTION_PREFIX,
    VIDEO_DIGITS,
    VIDEO_PREFIX,
)

T = TypeVar("T")

#: The narrative always happens inside one calendar year so dates stay plausible.
STORY_YEAR: int = 2024
#: The incident day is drawn from this window (day-of-year) so re-seeding moves
#: the whole story without ever landing on a leap-day edge.
INCIDENT_DAY_MIN: int = 40
INCIDENT_DAY_MAX: int = 300
#: Transactions are spread over this many days ending on the incident day.
TRANSACTION_WINDOW_DAYS: int = 120


class IdExhaustedError(RuntimeError):
    """Raised when a digit width cannot supply another unique identifier."""


@dataclass
class IdFactory:
    """Mints unique ids in the documented formats from one seeded stream.

    Numeric payloads are unique *across* families, so a bare ``82931`` in prose
    can only ever resolve to one entity - which is what makes the entity
    resolution ground truth unambiguous.
    """

    rng: random.Random
    _used_numbers: set[int]
    _used_ids: set[str]

    @classmethod
    def create(cls, rng: random.Random) -> IdFactory:
        return cls(rng=rng, _used_numbers=set(), _used_ids=set())

    def _number(self, digits: int) -> int:
        low = 10 ** (digits - 1)
        high = (10**digits) - 1
        span = high - low + 1
        for _ in range(span):
            candidate = self.rng.randint(low, high)
            if candidate not in self._used_numbers:
                self._used_numbers.add(candidate)
                return candidate
        raise IdExhaustedError(f"no unused {digits}-digit identifier remains")

    def _make(self, prefix: str, digits: int) -> str:
        value = f"{prefix}{self._number(digits)}"
        if value in self._used_ids:  # pragma: no cover - guarded by _used_numbers
            raise IdExhaustedError(f"duplicate identifier generated: {value}")
        self._used_ids.add(value)
        return value

    def customer(self) -> str:
        return self._make(CUSTOMER_PREFIX, CUSTOMER_DIGITS)

    def transaction(self) -> str:
        return self._make(TRANSACTION_PREFIX, TRANSACTION_DIGITS)

    def incident(self) -> str:
        return self._make(INCIDENT_PREFIX, INCIDENT_DIGITS)

    def asset(self) -> str:
        return self._make(ASSET_PREFIX, ASSET_DIGITS)

    def document(self) -> str:
        return self._make(DOCUMENT_PREFIX, DOCUMENT_DIGITS)

    def image(self) -> str:
        return self._make(IMAGE_PREFIX, IMAGE_DIGITS)

    def video(self) -> str:
        return self._make(VIDEO_PREFIX, VIDEO_DIGITS)

    def audio(self) -> str:
        return self._make(AUDIO_PREFIX, AUDIO_DIGITS)


def digits_of(identifier: str) -> str:
    """``'TX82931' -> '82931'`` - the bare numeric payload used in prose variants."""
    return "".join(character for character in identifier if character.isdigit())


def make_rng(seed: int, stream: str) -> random.Random:
    """Derive an independent, reproducible stream from the master seed.

    Separate streams mean adding a document does not shift the ids a later
    stage draws, so regenerating stays stable under change.
    """
    return random.Random(f"spectra::{seed}::{stream}")


def incident_moment(rng: random.Random) -> datetime:
    """The instant the narrative pivots on, drawn deterministically."""
    day = rng.randint(INCIDENT_DAY_MIN, INCIDENT_DAY_MAX)
    base = datetime(STORY_YEAR, 1, 1, tzinfo=timezone.utc) + timedelta(days=day - 1)
    return base.replace(hour=1, minute=12, second=0, microsecond=0)


def pick(rng: random.Random, options: Sequence[T]) -> T:
    if not options:
        raise ValueError("cannot pick from an empty sequence")
    return options[rng.randrange(len(options))]


def sample(rng: random.Random, options: Sequence[T], count: int) -> tuple[T, ...]:
    if count > len(options):
        raise ValueError(f"cannot sample {count} items from {len(options)}")
    return tuple(rng.sample(list(options), count))


def money(rng: random.Random, low: float, high: float) -> float:
    return round(rng.uniform(low, high), 2)


def iso(moment: datetime) -> str:
    """UTC ISO-8601 with a trailing ``Z`` - the corpus-wide timestamp format."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def human_date(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%d %B %Y")


def iso_date(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d")


def clock(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%H:%M")
