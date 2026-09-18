"""Snippet extraction: a real window of source text with the query terms marked.

No truncation-from-the-start placeholders - the window is centred on the densest
cluster of matched terms so the analyst sees *why* the chunk was retrieved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Characters of context returned around the best match.  Wide enough to carry a
#: full sentence of justification, narrow enough for a result list.
SNIPPET_WINDOW_CHARS = 240

#: Terms shorter than this are stop-word-like and never worth marking.
MIN_TERM_CHARS = 3

MARK_OPEN = "«"
MARK_CLOSE = "»"
ELLIPSIS = "…"

_WORD = re.compile(r"[A-Za-z0-9#]+")
_STOPWORDS = frozenset(
    {"the", "and", "for", "why", "did", "was", "were", "what", "when", "who", "how", "with", "from", "that",
     "this", "are", "has", "have", "does", "any", "all", "its", "our", "their"}
)


@dataclass(frozen=True)
class _Occurrence:
    start: int
    end: int


def query_terms(query: str, extra: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Distinct, meaningful terms to highlight, longest first."""
    tokens = [token.lower() for token in _WORD.findall(query)]
    tokens.extend(token.lower() for token in extra)
    unique = {token for token in tokens if len(token) >= MIN_TERM_CHARS and token not in _STOPWORDS}
    return tuple(sorted(unique, key=len, reverse=True))


def build_snippet(text: str, terms: tuple[str, ...], *, window: int = SNIPPET_WINDOW_CHARS) -> str:
    """Return a window of ``text`` centred on the best term cluster, terms marked."""
    cleaned = " ".join(text.split())
    if not cleaned:
        return ""
    occurrences = _find_occurrences(cleaned, terms)
    if not occurrences:
        head = cleaned[:window]
        return head + (ELLIPSIS if len(cleaned) > window else "")
    centre = _best_centre(occurrences, window)
    start = max(0, min(centre - window // 2, max(0, len(cleaned) - window)))
    end = min(len(cleaned), start + window)
    start, end = _snap_to_words(cleaned, start, end)
    body = _mark(cleaned, start, end, occurrences)
    return f"{ELLIPSIS if start > 0 else ''}{body}{ELLIPSIS if end < len(cleaned) else ''}"


def _find_occurrences(text: str, terms: tuple[str, ...]) -> tuple[_Occurrence, ...]:
    lowered = text.lower()
    found: list[_Occurrence] = []
    for term in terms:
        start = lowered.find(term)
        while start >= 0:
            found.append(_Occurrence(start, start + len(term)))
            start = lowered.find(term, start + len(term))
    return tuple(sorted(_drop_overlaps(found), key=lambda item: item.start))


def _drop_overlaps(found: list[_Occurrence]) -> list[_Occurrence]:
    kept: list[_Occurrence] = []
    for occurrence in sorted(found, key=lambda item: (item.start, -(item.end - item.start))):
        if kept and occurrence.start < kept[-1].end:
            continue
        kept.append(occurrence)
    return kept


def _best_centre(occurrences: tuple[_Occurrence, ...], window: int) -> int:
    """Centre of the window covering the most occurrences."""
    half = window // 2
    best_index, best_count = 0, -1
    for index, occurrence in enumerate(occurrences):
        count = sum(1 for other in occurrences if abs(other.start - occurrence.start) <= half)
        if count > best_count:
            best_index, best_count = index, count
    chosen = occurrences[best_index]
    return (chosen.start + chosen.end) // 2


def _snap_to_words(text: str, start: int, end: int) -> tuple[int, int]:
    while start > 0 and text[start - 1] != " ":
        start -= 1
    while end < len(text) and text[end - 1] != " " and text[end] != " ":
        end += 1
    return start, end


def _mark(text: str, start: int, end: int, occurrences: tuple[_Occurrence, ...]) -> str:
    pieces: list[str] = []
    cursor = start
    for occurrence in occurrences:
        if occurrence.start < start or occurrence.end > end:
            continue
        pieces.append(text[cursor : occurrence.start])
        pieces.append(f"{MARK_OPEN}{text[occurrence.start : occurrence.end]}{MARK_CLOSE}")
        cursor = occurrence.end
    pieces.append(text[cursor:end])
    return "".join(pieces)
