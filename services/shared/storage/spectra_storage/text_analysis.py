"""Analysis chain for the embedded BM25 index: tokenise, normalise, highlight.

Enterprise investigation queries are dominated by *identifiers* ("TX82931",
"INC-4471", "acct 0099") mixed with natural language.  A stemmer that mangles
identifiers destroys exactly the queries that matter most, so the analyser keeps
any token containing a digit verbatim and only applies suffix normalisation to
pure alphabetic words.  Indexing and querying share this module, which is what
guarantees the two sides agree.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

TOKEN_RE = re.compile(r"\w+", re.UNICODE)

MIN_STEM_LENGTH = 3
MIN_ING_LENGTH = 6
MIN_ED_LENGTH = 5
MIN_S_LENGTH = 4
HIGHLIGHT_RADIUS = 90
MAX_HIGHLIGHTS = 3
HIGHLIGHT_OPEN = "<em>"
HIGHLIGHT_CLOSE = "</em>"
ELLIPSIS = "..."
_DOUBLE_CONSONANT_RE = re.compile(r"([bcdfgklmnprstvz])\1$")
_ES_STEM_SUFFIXES = ("s", "x", "z", "ch", "sh")

STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "did", "do", "does",
        "for", "from", "had", "has", "have", "he", "her", "his", "how", "i", "if", "in", "into",
        "is", "it", "its", "of", "on", "or", "she", "should", "so", "than", "that", "the",
        "their", "them", "then", "there", "these", "they", "this", "to", "was", "were", "what",
        "when", "where", "which", "who", "why", "will", "with", "would", "you", "your",
    }
)


def is_identifier(token: str) -> bool:
    """Tokens containing a digit are treated as opaque identifiers."""
    return any(character.isdigit() for character in token)


def normalise(token: str) -> str:
    """Lowercase plus light suffix stripping; identifiers are returned intact."""
    lowered = token.lower()
    if is_identifier(lowered) or len(lowered) <= MIN_STEM_LENGTH:
        return lowered
    return _strip_suffix(lowered)


def _strip_suffix(word: str) -> str:
    if word.endswith("ies") and len(word) > MIN_S_LENGTH:
        return f"{word[:-3]}y"
    if word.endswith("ing") and len(word) >= MIN_ING_LENGTH:
        return _undouble(word[:-3])
    if word.endswith("ed") and len(word) >= MIN_ED_LENGTH:
        return _undouble(word[:-2])
    if word.endswith("es") and len(word) >= MIN_S_LENGTH:
        stem = word[:-2]
        return stem if stem.endswith(_ES_STEM_SUFFIXES) else word[:-1]
    if word.endswith("s") and not word.endswith("ss") and len(word) >= MIN_S_LENGTH:
        return word[:-1]
    return word


def _undouble(stem: str) -> str:
    if len(stem) > MIN_STEM_LENGTH and _DOUBLE_CONSONANT_RE.search(stem):
        return stem[:-1]
    return stem


def spans(text: str) -> list[tuple[str, int, int]]:
    """Every accepted term with the character span of its original surface form."""
    found: list[tuple[str, int, int]] = []
    for match in TOKEN_RE.finditer(text or ""):
        raw = match.group(0)
        if raw.lower() in STOPWORDS:
            continue
        term = normalise(raw)
        if not term:
            continue
        found.append((term, match.start(), match.end()))
    return found


def tokenise(text: str) -> list[str]:
    """Analysed term stream used for both indexing and querying."""
    return [term for term, _start, _end in spans(text)]


def term_frequencies(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for term in tokenise(text):
        counts[term] = counts.get(term, 0) + 1
    return counts


def highlights(text: str, terms: Iterable[str], limit: int = MAX_HIGHLIGHTS) -> list[str]:
    """Snippets of ``text`` around the first ``limit`` matched query terms."""
    wanted = {t for t in terms if t}
    if not wanted or not text:
        return []
    windows = _match_windows(text, wanted, limit)
    return [_render_window(text, start, end, hits) for start, end, hits in windows]


def _match_windows(
    text: str, wanted: set[str], limit: int
) -> list[tuple[int, int, list[tuple[int, int]]]]:
    windows: list[tuple[int, int, list[tuple[int, int]]]] = []
    for term, start, end in spans(text):
        if term not in wanted:
            continue
        if windows and start <= windows[-1][1]:
            previous_start, previous_end, hits = windows[-1]
            windows[-1] = (previous_start, max(previous_end, end + HIGHLIGHT_RADIUS), [*hits, (start, end)])
            continue
        if len(windows) >= max(limit, 0):
            break
        windows.append((max(start - HIGHLIGHT_RADIUS, 0), end + HIGHLIGHT_RADIUS, [(start, end)]))
    return windows


def _render_window(text: str, start: int, end: int, hits: Sequence[tuple[int, int]]) -> str:
    clipped_end = min(end, len(text))
    pieces: list[str] = []
    cursor = start
    for hit_start, hit_end in hits:
        pieces.append(text[cursor:hit_start])
        pieces.append(f"{HIGHLIGHT_OPEN}{text[hit_start:hit_end]}{HIGHLIGHT_CLOSE}")
        cursor = hit_end
    pieces.append(text[cursor:clipped_end])
    prefix = ELLIPSIS if start > 0 else ""
    suffix = ELLIPSIS if clipped_end < len(text) else ""
    return f"{prefix}{''.join(pieces).strip()}{suffix}"
