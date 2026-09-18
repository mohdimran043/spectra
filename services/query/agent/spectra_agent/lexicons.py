"""Deterministic vocabulary used by the query router.

These lists are the fallback brain: when no LLM is reachable the router must
still classify intent, modality and time correctly, so the vocabulary is
explicit, inspectable and free of any corpus-specific identifier.
"""

from __future__ import annotations

import re
from collections.abc import Collection

from spectra_schemas import Modality

# Enterprise identifiers: a letter prefix glued to digits (ticket, order,
# transaction, incident refs), dotted/hyphenated refs, UUIDs and emails.
ID_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b[A-Z]{2,6}[-_/]?\d{3,}\b"),
    re.compile(r"\b\d{6,}\b"),
    re.compile(r"\b[A-Z]{2,6}-\d{1,}-[A-Z0-9]{2,}\b"),
)

TEMPORAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:yesterday|today|tonight|last night)\b", re.I),
    re.compile(r"\b(?:last|past|previous|next)\s+(?:week|month|quarter|year|\d+\s+days?)\b", re.I),
    re.compile(r"\b(?:before|after|between|since|until|during)\b\s+\S+", re.I),
    re.compile(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}?\b", re.I),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b(?:19|20)\d{2}\b"),
    re.compile(r"\b(?:timeline|chronolog\w+|sequence of events|when did|what happened)\b", re.I),
)

MODALITY_TERMS: dict[Modality, tuple[str, ...]] = {
    Modality.VIDEO: (
        "video", "footage", "clip", "camera", "cctv", "recording of", "screen recording",
        "frame", "scene", "filmed", "on camera",
    ),
    Modality.IMAGE: (
        "image", "photo", "photograph", "picture", "screenshot", "diagram", "chart",
        "figure", "scan", "logo", "snapshot", "whiteboard",
    ),
    Modality.AUDIO: (
        "audio", "said", "says", "spoken", "call", "voicemail", "transcript", "recorded call",
        "meeting recording", "podcast", "voice", "dictation", "who mentioned",
    ),
    Modality.DOCUMENT: (
        "document", "report", "pdf", "policy", "contract", "email", "memo", "invoice",
        "spreadsheet", "slide", "presentation", "manual", "write-up", "ticket",
    ),
    Modality.DATABASE: (
        "record", "row", "table", "database", "ledger entry", "account", "status of",
        "customer record", "transaction record",
    ),
}

AGGREGATION_TERMS: tuple[str, ...] = (
    "how many", "count", "number of", "total", "sum", "average", "median", "list all",
    "top ", "breakdown", "per month", "per day", "group by", "distribution",
)

CONTRADICTION_TERMS: tuple[str, ...] = (
    "contradict", "inconsistent", "inconsistency", "conflict", "discrepan", "mismatch",
    "disagree", "does not match", "doesn't match", "differs from",
)

INVESTIGATION_TERMS: tuple[str, ...] = (
    "why", "root cause", "investigate", "investigation", "what caused", "what led to",
    "how did", "explain the failure", "reason for", "diagnose", "get to the bottom",
)

COMPARISON_TERMS: tuple[str, ...] = (
    "compare", "comparison", "versus", " vs ", "difference between", "differences between",
    "better than", "relative to",
)

MEDIA_LOCATION_TERMS: tuple[str, ...] = (
    "show me the", "find the video", "which frame", "where in the video", "at what timestamp",
    "locate the", "point me to the", "which screenshot", "which image",
)

STOPWORDS: frozenset[str] = frozenset(
    """a an the and or but if then than that this these those of to in on at by for with
    from as is are was were be been being do does did done have has had it its into about
    over under again further once here there all any both each few more most other some
    such no nor not only own same so too very can will just should now what which who whom
    when where why how me my we our you your they them their i""".split()
)

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{1,}")


def detect_ids(text: str) -> list[str]:
    """Enterprise identifiers present in ``text`` - order preserved, deduplicated."""
    found: list[str] = []
    for pattern in ID_PATTERNS:
        for match in pattern.findall(text):
            value = match if isinstance(match, str) else match[0]
            if value and value not in found and not _is_plain_year(value):
                found.append(value)
    return found


def _is_plain_year(value: str) -> bool:
    return bool(re.fullmatch(r"(?:19|20)\d{2}", value))


def temporal_hint(text: str) -> str | None:
    for pattern in TEMPORAL_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(0).strip()
    return None


def target_modalities(text: str) -> list[Modality]:
    lowered = text.lower()
    hits = [modality for modality, terms in MODALITY_TERMS.items() if any(t in lowered for t in terms)]
    return hits


def contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)


def keywords(text: str, limit: int = 12) -> list[str]:
    """Content words, deduplicated, in first-appearance order."""
    out: list[str] = []
    for token in _WORD.findall(text):
        lowered = token.lower()
        if lowered in STOPWORDS or len(lowered) < 3 or lowered in out:
            continue
        out.append(lowered)
        if len(out) >= limit:
            break
    return out


def content_tokens(text: str) -> set[str]:
    return {t.lower() for t in _WORD.findall(text) if t.lower() not in STOPWORDS and len(t) > 2}


def token_overlap(left: Collection[str], right: Collection[str]) -> float:
    """Jaccard overlap of two token sets - how much two statements say the same thing."""
    first, second = set(left), set(right)
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)
