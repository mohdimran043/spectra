"""Deterministic text helpers shared by the builder, timeline and radar.

Everything here is *extractive*: it selects spans that already exist in the
source text.  No sentence is ever generated, so an evidence summary can always
be traced back to a literal excerpt of the retrieved chunk.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from functools import lru_cache

from .lexicons import INFORMATIVE_KEYWORDS

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_WHITESPACE = re.compile(r"\s+")
_KEY_VALUE = re.compile(
    r"(?P<key>[A-Za-z][A-Za-z0-9_ ]{0,30}?)\s*[=:]\s*\"?(?P<value>[A-Za-z0-9_.,$£€%+\-]+)\"?"
)

# A summary shorter than this is usually a fragment ("Page 14"); longer than
# ~240 characters it stops being quotable in a citation panel.
MIN_SENTENCE_CHARS = 20
MAX_SUMMARY_CHARS = 240
MAX_EXCERPT_CHARS = 600

# Scoring weights for picking the most informative sentence.  Naming the target
# entity dominates: a sentence that does not mention it cannot be attributed.
ENTITY_MENTION_SCORE = 2.0
INFORMATIVE_KEYWORD_SCORE = 0.5
DIGIT_SCORE = 0.4
LENGTH_PENALTY = 0.5
# Earlier sentences win ties, which keeps summaries stable across re-runs.
POSITION_TIEBREAK = 0.01


@lru_cache(maxsize=4096)
def term_pattern(term: str) -> re.Pattern[str]:
    """Word-boundary, case-insensitive matcher for one surface form."""
    return re.compile(rf"(?<!\w){re.escape(term.strip())}(?!\w)", re.IGNORECASE)


def normalise_whitespace(text: str) -> str:
    return _WHITESPACE.sub(" ", text or "").strip()


def split_sentences(text: str) -> list[str]:
    """Split into sentences, preserving the original characters."""
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    parts = [normalise_whitespace(part) for part in _SENTENCE_SPLIT.split(cleaned)]
    return [part for part in parts if part]


def matched_terms(text: str, terms: Iterable[str]) -> list[str]:
    """Return the supplied terms that literally appear in ``text``."""
    body = text or ""
    found: list[str] = []
    for term in terms:
        cleaned = (term or "").strip()
        if cleaned and term_pattern(cleaned).search(body) and cleaned not in found:
            found.append(cleaned)
    return found


def mentions_any(text: str, terms: Iterable[str]) -> bool:
    return bool(matched_terms(text, terms))


def truncate(text: str, limit: int) -> str:
    cleaned = normalise_whitespace(text)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(limit - 1, 0)].rstrip() + "…"


def _sentence_score(sentence: str, terms: Sequence[str], position: int) -> float:
    lowered = sentence.lower()
    score = 0.0
    if matched_terms(sentence, terms):
        score += ENTITY_MENTION_SCORE
    score += INFORMATIVE_KEYWORD_SCORE * sum(1 for word in INFORMATIVE_KEYWORDS if word in lowered)
    if any(char.isdigit() for char in sentence):
        score += DIGIT_SCORE
    if len(sentence) < MIN_SENTENCE_CHARS or len(sentence) > MAX_SUMMARY_CHARS:
        score -= LENGTH_PENALTY
    return score - POSITION_TIEBREAK * position


def extractive_summary(text: str, terms: Sequence[str] = (), *, limit: int = MAX_SUMMARY_CHARS) -> str:
    """Pick the most informative *existing* sentence that names the target.

    Falls back to the most informative sentence overall when nothing mentions
    the entity, so the summary is always a literal span of the source.
    """
    sentences = split_sentences(text)
    if not sentences:
        return ""
    best_index = max(
        range(len(sentences)),
        key=lambda index: _sentence_score(sentences[index], terms, index),
    )
    return truncate(sentences[best_index], limit)


def excerpt_around(text: str, sentence: str, *, limit: int = MAX_EXCERPT_CHARS) -> str:
    """Return a literal window of ``text`` containing ``sentence``."""
    body = normalise_whitespace(text)
    if not body:
        return ""
    if len(body) <= limit:
        return body
    anchor = body.find(normalise_whitespace(sentence)[:60]) if sentence else -1
    if anchor < 0:
        return truncate(body, limit)
    half = limit // 2
    start = max(anchor - half, 0)
    return truncate(body[start : start + limit], limit)


def key_value_pairs(text: str) -> list[tuple[str, str]]:
    """Extract ``key=value`` / ``key: value`` pairs from record-style text."""
    pairs: list[tuple[str, str]] = []
    for match in _KEY_VALUE.finditer(text or ""):
        key = match.group("key").strip().lower().replace(" ", "_")
        value = match.group("value").strip().strip(".,")
        if key and value:
            pairs.append((key, value))
    return pairs


def tokens_before(sentence: str, index: int, count: int) -> list[str]:
    """The ``count`` word tokens immediately preceding character ``index``."""
    if count <= 0:
        return []
    prefix = sentence[:index].lower()
    return re.findall(r"[a-z']+", prefix)[-count:]


def parse_number(value: str) -> float | None:
    cleaned = re.sub(r"[^0-9.\-]", "", value or "")
    if not cleaned or cleaned in {"-", ".", "-."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None
