"""Deterministic canonicalisation of surface forms.

A canonical key is the contract between extraction and resolution: two surfaces
that denote the same thing MUST produce the same key, and the mapping must be
pure (no I/O, no model calls, no clock).  That is what lets the resolver answer
"is this the same transaction?" for free in the common case.

Identifier rules
----------------
1. Upper-case, then drop everything that is not a letter or a digit.  Spacing,
   ``#``, ``-`` and ``.`` carry no meaning in an enterprise id.
2. Split into an alphabetic prefix and a numeric tail.
3. Map the prefix through :data:`ID_PREFIX_SYNONYMS` (``TXN``/``TRANSACTION``/
   ``PAYMENTREFERENCE``/``REFERENCE`` -> ``TX``, ``CUSTOMER``/``CUST``/``CLIENT``
   -> ``C``, ...).  An empty or unknown prefix falls back to the canonical prefix
   of the requested :class:`EntityType`, which is what makes a bare number typed
   by context ("customer 82731") land on the same key as ``C82731``.
4. **Zero-pad rule:** leading zeros are stripped, then the number is left-padded
   back to the grammar's *minimum* width (customer/transaction 4, incident/asset
   3).  Padding to a fixed maximum width would corrupt genuinely longer ids, and
   not padding at all would make ``INC007`` and ``INC7`` different entities.

Person rules
------------
Names are compared through three keys of decreasing specificity so that
``Mohammed Imran``, ``M. Imran`` and ``Imran`` are all *comparable* without being
blindly merged: an order-insensitive full-token key, an initials+surname key and
a surname-only key.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from spectra_schemas import EntityType

from .patterns import HONORIFICS, ID_PATTERNS, PatternMatch, iter_pattern_matches

#: Surface prefix (already upper-cased and stripped) -> canonical prefix.
ID_PREFIX_SYNONYMS: dict[str, str] = {
    "TX": "TX",
    "TXN": "TX",
    "TRANS": "TX",
    "TRANSACTION": "TX",
    "TRANSACTIONS": "TX",
    "TRANSACTIONID": "TX",
    "PAYMENT": "TX",
    "PAYMENTREF": "TX",
    "PAYMENTREFERENCE": "TX",
    "PMTREF": "TX",
    "REF": "TX",
    "REFERENCE": "TX",
    "C": "C",
    "CUST": "C",
    "CUSTOMER": "C",
    "CUSTOMERS": "C",
    "CUSTOMERID": "C",
    "CLIENT": "C",
    "CLIENTS": "C",
    "ACCOUNTHOLDER": "C",
    "INC": "INC",
    "INCIDENT": "INC",
    "INCIDENTS": "INC",
    "TICKET": "INC",
    "CASE": "INC",
    "AST": "AST",
    "ASSET": "AST",
    "ASSETS": "AST",
    "EQUIPMENT": "AST",
    "DOC": "DOC",
    "DOCUMENT": "DOC",
    "VID": "VID",
    "VIDEO": "VID",
    "IMG": "IMG",
    "IMAGE": "IMG",
}

#: Canonical prefix and minimum digit width per identifier-bearing entity type.
TYPE_DEFAULTS: dict[EntityType, tuple[str, int]] = {
    EntityType.CUSTOMER: ("C", 4),
    EntityType.TRANSACTION: ("TX", 4),
    EntityType.INCIDENT: ("INC", 3),
    EntityType.ASSET: ("AST", 3),
}

#: Minimum digit width per canonical prefix (drives the zero-pad rule).
PREFIX_MIN_DIGITS: dict[str, int] = {p.canonical_prefix: p.min_digits for p in ID_PATTERNS}

PERSON_FULL_PREFIX = "person:full:"
PERSON_INITIALS_PREFIX = "person:init:"
PERSON_SURNAME_PREFIX = "person:last:"

_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")
_PREFIX_DIGITS = re.compile(r"^([A-Z]*)(\d+)$")
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class PersonKeys:
    """The comparable keys generated for one person surface form."""

    display: str
    tokens: tuple[str, ...]
    full: str
    initials: str
    surname: str

    def all_keys(self) -> tuple[str, ...]:
        """Most specific first - the resolver walks them in this order."""
        return (self.full, self.initials, self.surname)


@dataclass(frozen=True)
class EnterpriseId:
    """A canonical identifier recovered from free text."""

    entity_type: EntityType
    canonical: str
    surface: str
    start: int
    end: int
    confidence: float


def strip_accents(value: str) -> str:
    """``Müller`` -> ``Muller`` - accents never distinguish two enterprise people."""
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_surface(surface: str, entity_type: EntityType) -> str:
    """Return the deterministic canonical key for ``surface``."""
    if entity_type is EntityType.PERSON:
        return person_keys(surface).full
    if entity_type in TYPE_DEFAULTS:
        return normalize_identifier(surface, entity_type)
    return _normalize_text(surface)


def normalize_identifier(surface: str, entity_type: EntityType) -> str:
    """Canonicalise an identifier surface (``Txn 82931`` -> ``TX82931``)."""
    cleaned = _NON_ALNUM.sub("", strip_accents(surface)).upper()
    if not cleaned:
        return ""
    match = _PREFIX_DIGITS.match(cleaned)
    if match is None:
        return cleaned
    raw_prefix, digits = match.group(1), match.group(2)
    default_prefix, default_width = TYPE_DEFAULTS.get(entity_type, ("", 0))
    prefix = ID_PREFIX_SYNONYMS.get(raw_prefix, default_prefix if not raw_prefix else raw_prefix)
    width = PREFIX_MIN_DIGITS.get(prefix, default_width)
    return f"{prefix}{_pad(digits, width)}"


def person_keys(surface: str) -> PersonKeys:
    """Build the three comparable keys for a person name."""
    tokens = _person_tokens(surface)
    if not tokens:
        empty = _normalize_text(surface)
        return PersonKeys(display=surface.strip(), tokens=(), full=empty, initials=empty, surname=empty)
    surname = tokens[-1]
    given_initials = "".join(sorted(token[0] for token in tokens[:-1]))
    return PersonKeys(
        display=_WHITESPACE.sub(" ", surface.strip()),
        tokens=tokens,
        full=PERSON_FULL_PREFIX + "|".join(sorted(tokens)),
        initials=f"{PERSON_INITIALS_PREFIX}{given_initials}|{surname}",
        surname=PERSON_SURNAME_PREFIX + surname,
    )


def normalized_keys_for(surface: str, entity_type: EntityType) -> tuple[str, ...]:
    """Every key under which ``surface`` may be stored or looked up."""
    if entity_type is EntityType.PERSON:
        return person_keys(surface).all_keys()
    return (normalize_surface(surface, entity_type),)


def enterprise_ids(text: str) -> tuple[EnterpriseId, ...]:
    """Canonical enterprise ids present in ``text``, de-duplicated.

    The search layer uses this to decide whether a query deserves an exact-id
    lookup; it is pure regex plus string work, so it costs nothing at query time.
    """
    found: dict[str, EnterpriseId] = {}
    for match in iter_pattern_matches(text):
        if not match.pattern.min_digits:
            continue
        canonical = _canonical_from_match(match)
        if not canonical:
            continue
        existing = found.get(canonical)
        if existing is None or match.pattern.confidence > existing.confidence:
            found[canonical] = EnterpriseId(
                entity_type=match.pattern.entity_type,
                canonical=canonical,
                surface=match.surface,
                start=match.start,
                end=match.end,
                confidence=match.pattern.confidence,
            )
    return tuple(found.values())


def _canonical_from_match(match: PatternMatch) -> str:
    prefix = match.pattern.canonical_prefix
    digits = match.digits
    if not digits:
        return ""
    width = PREFIX_MIN_DIGITS.get(prefix, match.pattern.min_digits)
    return f"{prefix}{_pad(digits, width)}"


def _pad(digits: str, width: int) -> str:
    trimmed = digits.lstrip("0") or "0"
    return trimmed.rjust(width, "0") if width > 0 else trimmed


def _person_tokens(surface: str) -> tuple[str, ...]:
    cleaned = strip_accents(surface).casefold()
    cleaned = cleaned.replace(".", " ").replace("-", " ").replace("'", "")
    parts = [part for part in _NON_ALNUM.sub(" ", cleaned).split() if part]
    return tuple(part for part in parts if part not in HONORIFICS)


def _normalize_text(surface: str) -> str:
    cleaned = _WHITESPACE.sub(" ", _NON_ALNUM.sub(" ", strip_accents(surface)).strip())
    return cleaned.upper()
