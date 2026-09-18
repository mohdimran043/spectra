"""Enterprise identifier grammars.

Every enterprise identifier SPECTRA understands is declared here **once**, as a
named pattern carrying its :class:`EntityType`, its canonical prefix and a
calibrated confidence.  Extraction, normalisation and the search layer's
"is there an exact ID in this query?" probe all read this single table, so a new
identifier family is a one-entry change rather than a grep-and-patch exercise.

The *variant* forms matter as much as the canonical one: an investigation corpus
writes the same transaction as ``TX82931``, ``Txn 82931``, ``Transaction #82931``
and ``Payment reference 82931``.  Each variant is a pattern here and every one of
them normalises onto the same canonical key (see :mod:`.normalize`).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from spectra_schemas import EntityType

# ---------------------------------------------------------------------------
# Confidence calibration.
#
# These are not arbitrary: they encode how much syntactic evidence the surface
# form carries.  A literal canonical id ("TX82931") is self-identifying and can
# only be a transaction, so it sits just below 1.0 (never exactly 1.0 - OCR and
# ASR can both hallucinate a digit).  A prefixed form ("Transaction #82931")
# is explicit but relies on our synonym table.  A bare number that is only typed
# by a nearby keyword is the weakest reading and must stay clearly below the
# others so the resolver can prefer stronger mentions of the same span.
# ---------------------------------------------------------------------------
CONFIDENCE_CANONICAL_ID = 0.99
CONFIDENCE_PREFIXED_ID = 0.92
CONFIDENCE_CONTEXT_ID = 0.75
CONFIDENCE_DATE = 0.90
CONFIDENCE_SERVICE = 0.60
CONFIDENCE_PERSON_FULL = 0.80
CONFIDENCE_PERSON_INITIAL = 0.65
CONFIDENCE_PERSON_HONORIFIC = 0.70

# How far either side of a bare number the extractor looks for a type keyword.
# 40 characters covers "the payment for customer 82731 failed" without reaching
# into a neighbouring sentence, which is where false typings come from.
CONTEXT_WINDOW_CHARS = 40


@dataclass(frozen=True)
class EntityPattern:
    """One named identifier grammar."""

    name: str
    entity_type: EntityType
    regex: re.Pattern[str]
    confidence: float
    description: str
    canonical_prefix: str = ""
    min_digits: int = 0
    value_group: int = 1

    def digits_of(self, match: re.Match[str]) -> str:
        """The numeric payload of a match, or ``""`` for non-numeric grammars."""
        if self.min_digits <= 0:
            return ""
        try:
            return match.group(self.value_group) or ""
        except IndexError:  # pragma: no cover - defensive, grammars declare their group
            return ""


# ---------------------------------------------------------------------------
# Identifier grammars.  Order matters only for readability: overlapping spans
# are resolved by the extractor (longest span, then highest confidence).
# ---------------------------------------------------------------------------
CUSTOMER_CANONICAL = EntityPattern(
    name="customer_canonical",
    entity_type=EntityType.CUSTOMER,
    regex=re.compile(r"\bC(\d{4,8})\b"),
    confidence=CONFIDENCE_CANONICAL_ID,
    description="Canonical customer id, e.g. C82731",
    canonical_prefix="C",
    min_digits=4,
)
CUSTOMER_PREFIXED = EntityPattern(
    name="customer_prefixed",
    entity_type=EntityType.CUSTOMER,
    regex=re.compile(r"\b(?:customers?|cust|clients?|account holder)\s*(?:id|no\.?|number)?\s*[:#]?\s*(\d{4,8})\b", re.IGNORECASE),
    confidence=CONFIDENCE_PREFIXED_ID,
    description="Spelled-out customer reference, e.g. 'Customer 82731', 'cust #82731'",
    canonical_prefix="C",
    min_digits=4,
)
TRANSACTION_CANONICAL = EntityPattern(
    name="transaction_canonical",
    entity_type=EntityType.TRANSACTION,
    regex=re.compile(r"\bTX(\d{4,8})\b", re.IGNORECASE),
    confidence=CONFIDENCE_CANONICAL_ID,
    description="Canonical transaction id, e.g. TX82931",
    canonical_prefix="TX",
    min_digits=4,
)
TRANSACTION_PREFIXED = EntityPattern(
    name="transaction_prefixed",
    entity_type=EntityType.TRANSACTION,
    regex=re.compile(
        r"\b(?:txn|trans|transactions?|payment\s+reference|payment\s+ref|pmt\s+ref|reference)"
        r"\s*(?:id|no\.?|number)?\s*[:#]?\s*(\d{4,8})\b",
        re.IGNORECASE,
    ),
    confidence=CONFIDENCE_PREFIXED_ID,
    description="Spelled-out transaction reference: 'Txn 82931', 'Transaction #82931', 'Payment reference 82931'",
    canonical_prefix="TX",
    min_digits=4,
)
INCIDENT_CANONICAL = EntityPattern(
    name="incident_canonical",
    entity_type=EntityType.INCIDENT,
    regex=re.compile(r"\bINC(\d{3,8})\b", re.IGNORECASE),
    confidence=CONFIDENCE_CANONICAL_ID,
    description="Canonical incident id, e.g. INC1829",
    canonical_prefix="INC",
    min_digits=3,
)
INCIDENT_PREFIXED = EntityPattern(
    name="incident_prefixed",
    entity_type=EntityType.INCIDENT,
    regex=re.compile(r"\b(?:incidents?|tickets?|cases?)\s*(?:id|no\.?|number)?\s*[:#]?\s*(\d{3,8})\b", re.IGNORECASE),
    confidence=CONFIDENCE_PREFIXED_ID,
    description="Spelled-out incident reference, e.g. 'Incident #1829'",
    canonical_prefix="INC",
    min_digits=3,
)
ASSET_CANONICAL = EntityPattern(
    name="asset_canonical",
    entity_type=EntityType.ASSET,
    regex=re.compile(r"\bAST(\d{3,8})\b", re.IGNORECASE),
    confidence=CONFIDENCE_CANONICAL_ID,
    description="Canonical enterprise asset id, e.g. AST4412",
    canonical_prefix="AST",
    min_digits=3,
)
ASSET_PREFIXED = EntityPattern(
    name="asset_prefixed",
    entity_type=EntityType.ASSET,
    regex=re.compile(r"\b(?:assets?|equipment)\s*(?:id|no\.?|number|tag)?\s*[:#]?\s*(\d{3,8})\b", re.IGNORECASE),
    confidence=CONFIDENCE_PREFIXED_ID,
    description="Spelled-out asset reference, e.g. 'Asset tag 4412'",
    canonical_prefix="AST",
    min_digits=3,
)
DOCUMENT_ID = EntityPattern(
    name="document_id",
    entity_type=EntityType.ASSET,
    regex=re.compile(r"\bDOC(\d{3,8})\b", re.IGNORECASE),
    confidence=CONFIDENCE_CANONICAL_ID,
    description="Document identifier, e.g. DOC2201",
    canonical_prefix="DOC",
    min_digits=3,
)
VIDEO_ID = EntityPattern(
    name="video_id",
    entity_type=EntityType.ASSET,
    regex=re.compile(r"\bVID(\d{3,8})\b", re.IGNORECASE),
    confidence=CONFIDENCE_CANONICAL_ID,
    description="Video identifier, e.g. VID0417",
    canonical_prefix="VID",
    min_digits=3,
)
IMAGE_ID = EntityPattern(
    name="image_id",
    entity_type=EntityType.ASSET,
    regex=re.compile(r"\bIMG(\d{3,8})\b", re.IGNORECASE),
    confidence=CONFIDENCE_CANONICAL_ID,
    description="Image identifier, e.g. IMG0912",
    canonical_prefix="IMG",
    min_digits=3,
)
SERVICE_NAME = EntityPattern(
    name="service_name",
    entity_type=EntityType.SERVICE,
    regex=re.compile(r"\b([a-z][a-z0-9]*(?:-[a-z0-9]+)*-(?:service|svc|api|gateway|worker|db))\b", re.IGNORECASE),
    confidence=CONFIDENCE_SERVICE,
    description="Kebab-case service name, e.g. payment-gateway, billing-service",
)
DATE_ISO = EntityPattern(
    name="date_iso",
    entity_type=EntityType.EVENT,
    regex=re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"),
    confidence=CONFIDENCE_DATE,
    description="ISO-8601 calendar date, e.g. 2024-03-11",
)
DATE_LONG = EntityPattern(
    name="date_long",
    entity_type=EntityType.EVENT,
    regex=re.compile(
        r"\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4})\b",
        re.IGNORECASE,
    ),
    confidence=CONFIDENCE_DATE,
    description="Long-form date, e.g. 11 March 2024",
)

#: Grammars that yield a canonical enterprise identifier (prefix + digits).
ID_PATTERNS: tuple[EntityPattern, ...] = (
    CUSTOMER_CANONICAL,
    CUSTOMER_PREFIXED,
    TRANSACTION_CANONICAL,
    TRANSACTION_PREFIXED,
    INCIDENT_CANONICAL,
    INCIDENT_PREFIXED,
    ASSET_CANONICAL,
    ASSET_PREFIXED,
    DOCUMENT_ID,
    VIDEO_ID,
    IMAGE_ID,
)

#: Everything else the regex pass recognises.
DESCRIPTIVE_PATTERNS: tuple[EntityPattern, ...] = (SERVICE_NAME, DATE_ISO, DATE_LONG)

ALL_PATTERNS: tuple[EntityPattern, ...] = ID_PATTERNS + DESCRIPTIVE_PATTERNS

#: Keyword -> type table used by the extractor's context-window typing pass for
#: bare numbers that no grammar above claimed.
CONTEXT_KEYWORDS: dict[EntityType, tuple[str, ...]] = {
    EntityType.CUSTOMER: ("customer", "client", "account holder", "subscriber"),
    EntityType.TRANSACTION: ("transaction", "txn", "payment", "charge", "refund", "reference"),
    EntityType.INCIDENT: ("incident", "ticket", "outage", "case"),
    EntityType.ASSET: ("asset", "equipment", "device", "terminal"),
}

#: Honorifics stripped before a person key is built.
HONORIFICS: frozenset[str] = frozenset(
    {"mr", "mrs", "ms", "miss", "dr", "prof", "professor", "eng", "engineer", "sir", "sheikh", "shaikh"}
)

#: Capitalised tokens that look like names but never are.  Keeping this list
#: small and enterprise-flavoured is deliberate: over-filtering loses real names.
PERSON_STOPWORDS: frozenset[str] = frozenset(
    {
        "the", "and", "for", "from", "with", "this", "that", "payment", "gateway", "service",
        "transaction", "customer", "incident", "asset", "report", "summary", "review", "database",
        "record", "video", "image", "document", "audio", "monday", "tuesday", "wednesday",
        "thursday", "friday", "saturday", "sunday", "january", "february", "march", "april",
        "may", "june", "july", "august", "september", "october", "november", "december",
        "support", "engineering", "finance", "operations", "team", "meeting", "call", "postmortem",
        "root", "cause", "analysis", "system", "platform", "invoice", "refund", "account", "north",
        "south", "east", "west", "region", "europe", "asia", "america",
    }
)

#: A capitalised token or a single-letter initial, e.g. ``Mohammed`` or ``M.``
_NAME_TOKEN = r"(?:[A-Z][a-z]{1,20}|[A-Z]\.)"

#: Two to four name tokens in a row - "Mohammed Imran", "M. Imran", "Anna-Lena Roth".
PERSON_SEQUENCE = re.compile(rf"\b{_NAME_TOKEN}(?:\s+{_NAME_TOKEN}){{1,3}}\b")

#: A single name token introduced by an honorific - "Dr Imran".
PERSON_HONORIFIC = re.compile(
    r"\b(?:Mr|Mrs|Ms|Miss|Dr|Prof|Professor|Eng|Sir|Sheikh)\.?\s+([A-Z][a-z]{1,20}(?:\s+[A-Z][a-z]{1,20}){0,3})\b"
)

#: Bare numbers considered by the context-window typing pass.
BARE_NUMBER = re.compile(r"\b(\d{3,8})\b")


@dataclass(frozen=True)
class PatternMatch:
    """One raw regex hit, before overlap resolution."""

    pattern: EntityPattern
    surface: str
    start: int
    end: int
    digits: str


def iter_pattern_matches(text: str) -> Iterator[PatternMatch]:
    """Yield every hit of every declared grammar, in no particular order."""
    for pattern in ALL_PATTERNS:
        for match in pattern.regex.finditer(text):
            yield PatternMatch(
                pattern=pattern,
                surface=match.group(0),
                start=match.start(),
                end=match.end(),
                digits=pattern.digits_of(match) if pattern.min_digits else "",
            )


def pattern_by_name(name: str) -> EntityPattern | None:
    for pattern in ALL_PATTERNS:
        if pattern.name == name:
            return pattern
    return None
