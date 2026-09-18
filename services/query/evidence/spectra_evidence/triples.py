"""Extraction of ``(entity, attribute, value)`` assertions from evidence text.

This is deliberately mechanical: configurable lexicons, word-boundary matching
and a negation window.  No model is asked what a document "means", so the same
text always yields the same assertions and a contradiction can be pointed at the
exact sentence that produced it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from spectra_config.logging import get_logger
from spectra_schemas import EvidenceItem

from .lexicons import (
    ATTRIBUTE_LEXICON,
    NEGATION_CUES,
    NEGATION_WINDOW_TOKENS,
    NUMERIC_ATTRIBUTES,
)
from .text_utils import (
    key_value_pairs,
    matched_terms,
    parse_number,
    split_sentences,
    term_pattern,
    tokens_before,
)

log = get_logger(__name__)

Lexicon = Mapping[str, Mapping[str, tuple[str, ...]]]


@dataclass(frozen=True)
class AttributeClaim:
    """One asserted fact, traceable to the sentence it came from."""

    evidence_id: str
    entity: str
    attribute: str
    value: str
    negated: bool
    sentence: str
    numeric: float | None = None

    def key(self) -> tuple[str, str]:
        return self.entity, self.attribute


def canonical_value(values: Mapping[str, tuple[str, ...]], raw: str) -> str | None:
    """Map a surface form onto its canonical value for one attribute."""
    lowered = (raw or "").strip().lower()
    if not lowered:
        return None
    for canonical, surfaces in values.items():
        if lowered == canonical or lowered in {surface.lower() for surface in surfaces}:
            return canonical
    return None


def attribute_for_value(lexicon: Lexicon, raw: str) -> tuple[str, str] | None:
    """Find which attribute owns this value surface, e.g. 'FAILED' -> status."""
    for attribute, values in lexicon.items():
        canonical = canonical_value(values, raw)
        if canonical:
            return attribute, canonical
    return None


def extract_claims(
    item: EvidenceItem,
    entity_keys: Sequence[str] = (),
    *,
    lexicon: Lexicon = ATTRIBUTE_LEXICON,
) -> list[AttributeClaim]:
    """Extract every attribute assertion this evidence makes about the targets."""
    text = _evidence_text(item)
    fallback_entities = _fallback_entities(item, entity_keys, text)
    claims: list[AttributeClaim] = []
    seen: set[tuple[str, str, str, bool]] = set()
    for sentence in split_sentences(text):
        entities = matched_terms(sentence, entity_keys) or fallback_entities
        if not entities:
            continue
        for entity in entities:
            for claim in _claims_in_sentence(item.evidence_id, entity, sentence, lexicon):
                signature = (claim.entity, claim.attribute, claim.value, claim.negated)
                if signature in seen:
                    continue
                seen.add(signature)
                claims.append(claim)
    return claims


def _claims_in_sentence(
    evidence_id: str, entity: str, sentence: str, lexicon: Lexicon
) -> list[AttributeClaim]:
    return [
        *_claims_from_pairs(evidence_id, entity, sentence, lexicon),
        *_claims_from_prose(evidence_id, entity, sentence, lexicon),
    ]


def _claims_from_pairs(
    evidence_id: str, entity: str, sentence: str, lexicon: Lexicon
) -> list[AttributeClaim]:
    """``status=FAILED`` / ``amount: 482.19`` as written in record exports."""
    claims: list[AttributeClaim] = []
    for key, raw in key_value_pairs(sentence):
        if key in NUMERIC_ATTRIBUTES:
            number = parse_number(raw)
            if number is None:
                continue
            claims.append(
                AttributeClaim(evidence_id, entity, key, f"{number:g}", False, sentence, number)
            )
            continue
        values = lexicon.get(key)
        canonical = canonical_value(values, raw) if values else None
        attribute = key
        if canonical is None:
            resolved = attribute_for_value(lexicon, raw)
            if resolved is None:
                continue
            attribute, canonical = resolved
        claims.append(AttributeClaim(evidence_id, entity, attribute, canonical, False, sentence))
    return claims


def _claims_from_prose(
    evidence_id: str, entity: str, sentence: str, lexicon: Lexicon
) -> list[AttributeClaim]:
    """``was not approved`` / ``the service was unavailable`` in narrative text."""
    claims: list[AttributeClaim] = []
    for attribute, values in lexicon.items():
        for canonical, surfaces in values.items():
            for surface in surfaces:
                for match in term_pattern(surface).finditer(sentence):
                    negated = _is_negated(sentence, match.start())
                    claims.append(
                        AttributeClaim(evidence_id, entity, attribute, canonical, negated, sentence)
                    )
    return claims


def _is_negated(sentence: str, index: int) -> bool:
    tokens = tokens_before(sentence, index, NEGATION_WINDOW_TOKENS)
    for position, token in enumerate(tokens):
        if token not in NEGATION_CUES:
            continue
        # "failed" only negates in "failed to <verb>"; on its own it is a status.
        if token == "failed" and (position + 1 >= len(tokens) or tokens[position + 1] != "to"):
            continue
        return True
    return False


def _evidence_text(item: EvidenceItem) -> str:
    summary = (item.summary or "").strip()
    excerpt = (item.excerpt or "").strip()
    if not excerpt or excerpt in summary:
        return summary
    if summary and summary in excerpt:
        return excerpt
    return f"{summary} {excerpt}".strip()


def _fallback_entities(item: EvidenceItem, entity_keys: Sequence[str], text: str) -> list[str]:
    """Entity keys this evidence is about, when a sentence names none of them."""
    if not entity_keys:
        return list(item.entities)
    linked = [key for key in entity_keys if key in item.entities]
    return linked or matched_terms(text, entity_keys)


__all__ = ["AttributeClaim", "attribute_for_value", "canonical_value", "extract_claims"]
