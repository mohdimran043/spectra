"""Claim verification - deterministic first, model cross-check second.

Four deterministic checks decide whether a claim may be asserted.  An optional
model cross-check can only *withhold* support, never grant it, and when the
model is unavailable verification proceeds on the deterministic checks and says
so in its note.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from spectra_config import Settings, get_settings
from spectra_config.logging import get_logger
from spectra_schemas import (
    EvidenceItem,
    EvidenceLedger,
    EvidenceStance,
    ModelRole,
    VerificationResult,
)

from ...causal_lexicon import salient_terms
from ...llm import structured, text_messages
from ...thresholds import MIN_DIVERSITY, MIN_INDEPENDENT_SOURCES

log = get_logger(__name__)

_ID_TOKEN = re.compile(r"\b(?:[A-Z]{2,6}[-_]?\d{3,}|[A-Z][a-z]+(?:\s[A-Z][a-z]+)+)\b")

VERIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "supported": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["supported", "reason"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You check whether a claim is supported by the supplied evidence excerpts and nothing else. "
    "If the excerpts do not state it, answer supported=false. Reply with JSON only."
)

# The deterministic checks that must all pass before a claim may be asserted.
MANDATORY_CHECKS = ("entities_present", "independent_sources", "no_counter_evidence", "diversity")


class Verifier:
    """Verifies one claim against the evidence ledger."""

    def __init__(
        self,
        settings: Settings | None = None,
        gateway: Any | None = None,
        min_sources: int | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._gateway = gateway
        self._min_sources = min_sources or MIN_INDEPENDENT_SOURCES

    async def verify(
        self,
        claim: str,
        ledger: EvidenceLedger,
        ctx: Any | None = None,
        *,
        allow_llm: bool = True,
    ) -> VerificationResult:
        cited = _cited(claim, ledger)
        checks: dict[str, bool] = {}
        notes: list[str] = []

        missing_entities = _missing_entities(claim, cited)
        checks["entities_present"] = not missing_entities
        if missing_entities:
            notes.append(f"not found in cited evidence: {', '.join(missing_entities[:3])}")

        sources = {item.provenance.source_id for item in cited}
        checks["independent_sources"] = len(sources) >= self._min_sources
        if not checks["independent_sources"]:
            notes.append(f"{len(sources)} independent source(s), {self._min_sources} required")

        against = [i for i in cited if i.stance is EvidenceStance.CONTRADICTING]
        checks["no_counter_evidence"] = not against
        if against:
            notes.append(f"{len(against)} cited item(s) count against this claim")

        diversity = _diversity(cited)
        checks["diversity"] = diversity >= MIN_DIVERSITY
        if not checks["diversity"]:
            notes.append(f"evidence diversity {diversity:.2f} below {MIN_DIVERSITY:.2f}")

        supported = all(checks[name] for name in MANDATORY_CHECKS)
        if allow_llm and self._gateway is not None and cited:
            supported, checks, notes = await self._cross_check(claim, cited, supported, checks, notes)
        else:
            notes.append("deterministic checks only (no model cross-check)")

        confidence = _confidence(cited, checks)
        return VerificationResult(
            claim=claim,
            supported=supported,
            confidence=confidence,
            supporting_evidence=[i.evidence_id for i in cited if i.stance is not EvidenceStance.CONTRADICTING],
            contradicting_evidence=[i.evidence_id for i in cited if i.stance is EvidenceStance.CONTRADICTING],
            diversity=diversity,
            note="; ".join(notes) if notes else "all checks passed",
            checks=checks,
        )

    async def _cross_check(
        self,
        claim: str,
        cited: list[EvidenceItem],
        supported: bool,
        checks: dict[str, bool],
        notes: list[str],
    ) -> tuple[bool, dict[str, bool], list[str]]:
        excerpts = "\n".join(f"[E{i + 1}] {item.summary} :: {item.excerpt}" for i, item in enumerate(cited[:10]))
        outcome = await structured(
            self._gateway,
            messages=text_messages(SYSTEM_PROMPT, f"Claim: {claim}\nEvidence:\n{excerpts}"),
            schema=VERIFY_SCHEMA,
            role=ModelRole.DEEP_BRAIN,
            max_tokens=256,
        )
        updated = dict(checks)
        if not outcome.ok or outcome.data is None:
            notes.append(f"model cross-check unavailable ({outcome.reason}); deterministic checks only")
            return supported, updated, notes
        agreed = bool(outcome.data.get("supported"))
        updated["llm_cross_check"] = agreed
        if not agreed:
            notes.append(f"model cross-check withheld support: {str(outcome.data.get('reason'))[:160]}")
        return supported and agreed, updated, notes


def _cited(claim: str, ledger: EvidenceLedger) -> list[EvidenceItem]:
    """Items that actually talk about the claim, strongest first."""
    terms = salient_terms(claim)
    if not terms:
        return sorted(ledger.items, key=lambda i: i.weight, reverse=True)
    relevant = [
        item
        for item in ledger.items
        if any(term in f"{item.summary} {item.excerpt} {' '.join(item.entities)}".lower() for term in terms)
    ]
    return sorted(relevant or ledger.items, key=lambda i: i.weight, reverse=True)


def _missing_entities(claim: str, cited: Sequence[EvidenceItem]) -> list[str]:
    named = {token.strip() for token in _ID_TOKEN.findall(claim)}
    if not named:
        return []
    haystack = " ".join(f"{i.summary} {i.excerpt} {' '.join(i.entities)}" for i in cited).lower()
    return [name for name in sorted(named) if name.lower() not in haystack]


def _diversity(cited: Sequence[EvidenceItem]) -> float:
    """Diversity of the evidence actually cited for this claim."""
    if not cited:
        return 0.0
    return EvidenceLedger(items=list(cited)).diversity()


def _confidence(cited: Sequence[EvidenceItem], checks: dict[str, bool]) -> float:
    """Evidence strength, scaled by the fraction of checks that passed."""
    if not cited:
        return 0.0
    strength = sum(item.weight for item in cited[:4]) / min(len(cited), 4)
    passed = sum(1 for value in checks.values() if value) / max(len(checks), 1)
    return round(max(0.0, min(1.0, strength * passed)), 4)
