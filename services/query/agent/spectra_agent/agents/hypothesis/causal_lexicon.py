"""Causal vocabulary: candidate-cause mining, error codes and negation.

The hypothesis engine mines causes *out of the retrieved corpus* using this
vocabulary - a category only becomes a hypothesis when its terms actually occur
in the evidence.  The disproof agent uses the same table in reverse, turning a
category into the competing outcomes that would prove it wrong.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from ...lexicons import STOPWORDS


@dataclass(frozen=True)
class CausalCategory:
    """One family of enterprise failure causes."""

    key: str
    label: str
    terms: tuple[str, ...]
    signals: tuple[str, ...]
    counter_terms: tuple[str, ...]


CAUSAL_CATEGORIES: tuple[CausalCategory, ...] = (
    CausalCategory(
        key="funds",
        label="insufficient funds or credit limit",
        terms=("insufficient funds", "nsf", "balance too low", "credit limit", "overdraft", "low balance"),
        signals=("a balance or limit figure below the requested amount", "a decline reason naming funds or limit"),
        counter_terms=("sufficient balance", "funds available", "limit increased", "balance confirmed"),
    ),
    CausalCategory(
        key="timeout",
        label="timeout or slow downstream response",
        terms=("timeout", "timed out", "deadline exceeded", "no response", "took too long", "latency spike"),
        signals=("an elapsed-time figure above the configured limit", "a retry or abort entry in a log"),
        counter_terms=("responded within", "completed in", "no latency", "response time normal"),
    ),
    CausalCategory(
        key="authorisation",
        label="authorisation decline or permission denial",
        terms=("declined", "do not honour", "do not honor", "unauthorized", "unauthorised",
               "permission denied", "access denied", "auth failure", "forbidden"),
        signals=("a decline or denial code attached to the attempt", "an authorisation record with a refusal reason"),
        counter_terms=("approved", "authorised", "authorized", "permission granted", "access granted"),
    ),
    CausalCategory(
        key="network",
        label="network or connectivity fault",
        terms=("network error", "connection reset", "connection refused", "unreachable", "dns",
               "packet loss", "link down", "socket"),
        signals=("a connectivity error recorded at the time of the failure", "an interface or route event"),
        counter_terms=("connection stable", "network healthy", "link up", "reachable"),
    ),
    CausalCategory(
        key="configuration",
        label="configuration or deployment change",
        terms=("config change", "configuration change", "misconfigur", "deployment", "release",
               "rollout", "feature flag", "parameter change"),
        signals=("a change record timestamped before the failure", "a differing parameter between environments"),
        counter_terms=("no changes", "configuration unchanged", "rollback completed", "no deployment"),
    ),
    CausalCategory(
        key="capacity",
        label="throttling or capacity exhaustion",
        terms=("rate limit", "throttl", "quota", "capacity", "overload", "queue depth", "saturat"),
        signals=("a utilisation or queue figure at its ceiling", "a throttling or rejection counter"),
        counter_terms=("within quota", "capacity headroom", "no throttling", "load normal"),
    ),
    CausalCategory(
        key="data_quality",
        label="invalid or malformed data",
        terms=("invalid format", "validation error", "schema", "missing field", "malformed",
               "mismatch", "parse error", "wrong currency", "bad request"),
        signals=("a field named in a validation message", "two records disagreeing on the same field"),
        counter_terms=("validated", "schema matches", "fields complete", "format accepted"),
    ),
    CausalCategory(
        key="infrastructure",
        label="hardware or infrastructure fault",
        terms=("disk", "memory", "out of memory", "cpu", "power", "hardware", "node failure", "crash"),
        signals=("a resource or host alert around the failure window", "a restart or failover event"),
        counter_terms=("host healthy", "no alerts", "resources normal", "no restart"),
    ),
    CausalCategory(
        key="credentials",
        label="expired credential or certificate",
        terms=("expired", "certificate", "token expired", "credential", "key rotation", "revoked"),
        signals=("an expiry date preceding the failure", "a rotation or revocation record"),
        counter_terms=("valid until", "renewed", "certificate valid", "credentials current"),
    ),
    CausalCategory(
        key="risk_hold",
        label="fraud, sanction or risk hold",
        terms=("fraud", "risk hold", "blocked", "sanction", "suspicious", "manual review", "flagged"),
        signals=("a review or hold record naming the subject", "a risk score above the action threshold"),
        counter_terms=("cleared", "no hold", "risk score low", "released"),
    ),
    CausalCategory(
        key="process",
        label="manual or process error",
        terms=("manual", "operator error", "human error", "wrong entry", "keyed incorrectly",
               "procedure not followed", "training"),
        signals=("an operator action recorded before the failure", "a corrected entry or amendment"),
        counter_terms=("procedure followed", "entry correct", "no manual intervention"),
    ),
    CausalCategory(
        key="vendor",
        label="upstream vendor or third-party outage",
        terms=("vendor", "upstream", "third party", "third-party", "provider outage", "partner system",
               "external service"),
        signals=("a vendor status or incident notice covering the window", "an upstream error surfaced downstream"),
        counter_terms=("vendor operational", "upstream healthy", "no outage", "provider available"),
    ),
)

# Error codes as they appear in enterprise logs: HTTP statuses, E-codes,
# ERR_ constants and SCREAMING_SNAKE reason codes.  Deliberately excludes bare
# alphanumeric record ids so record references never become "causes".
ERROR_CODE_PATTERN = re.compile(
    r"\b(?:HTTP[ _-]?\d{3}|E-?\d{3,5}|ERR[_-][A-Z0-9]{2,}|[A-Z]{2,6}_[A-Z]{2,}(?:_[A-Z0-9]+)*)\b"
)

# Claim-level negation used to build disproof queries.
NEGATION_MAP: dict[str, tuple[str, ...]] = {
    "failed": ("succeeded", "completed successfully", "settled"),
    "failure": ("success", "successful completion"),
    "declined": ("approved", "accepted"),
    "rejected": ("accepted", "approved"),
    "missing": ("present", "recorded", "found"),
    "expired": ("valid", "renewed", "in date"),
    "blocked": ("released", "allowed", "cleared"),
    "unavailable": ("available", "online"),
    "down": ("up", "operational"),
    "error": ("success", "no error", "healthy"),
    "timeout": ("responded in time", "completed within limit"),
    "insufficient": ("sufficient", "adequate"),
    "invalid": ("valid", "accepted"),
    "delayed": ("on time", "delivered on schedule"),
    "increase": ("decrease", "unchanged"),
    "decrease": ("increase", "unchanged"),
    "caused": ("unrelated to", "independent of"),
}


def mine_categories(texts: list[str]) -> list[tuple[CausalCategory, list[str]]]:
    """Categories whose terms genuinely occur in ``texts``, with the terms found."""
    corpus = " \n".join(texts).lower()
    matched: list[tuple[CausalCategory, list[str]]] = []
    for category in CAUSAL_CATEGORIES:
        hits = [term for term in category.terms if term in corpus]
        if hits:
            matched.append((category, hits))
    return matched


def mine_error_codes(texts: list[str]) -> list[str]:
    """Distinct error codes that appear literally in the corpus."""
    found: list[str] = []
    for text in texts:
        for code in ERROR_CODE_PATTERN.findall(text):
            if code not in found:
                found.append(code)
    return found


def category_for_key(key: str) -> CausalCategory | None:
    return next((c for c in CAUSAL_CATEGORIES if c.key == key), None)


def negate(text: str) -> list[str]:
    """Negated readings of ``text`` built by antonym substitution."""
    lowered = text.lower()
    variants: list[str] = []
    for term, antonyms in NEGATION_MAP.items():
        if term not in lowered:
            continue
        for antonym in antonyms:
            candidate = re.sub(rf"\b{re.escape(term)}\b", antonym, lowered)
            if candidate != lowered and candidate not in variants:
                variants.append(candidate)
    return variants


def competing_outcomes(text: str) -> list[str]:
    """Counter-terms of every causal category mentioned in ``text``."""
    lowered = text.lower()
    out: list[str] = []
    for category in CAUSAL_CATEGORIES:
        if any(term in lowered for term in category.terms) or category.label in lowered:
            out.extend(t for t in category.counter_terms if t not in out)
    return out


def salient_terms(text: str, limit: int = 8) -> list[str]:
    tokens = [t.lower() for t in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text)]
    out: list[str] = []
    for token in tokens:
        if token in STOPWORDS or token in out:
            continue
        out.append(token)
        if len(out) >= limit:
            break
    return out


def disproof_queries(claim: str, signals: Sequence[str] = (), limit: int = 4) -> list[str]:
    """Queries whose *hits* would weaken ``claim``.

    Built from three angles: the negated claim, the competing outcomes of any
    causal category the claim names, and the absence of its predicted signals.
    """
    queries: list[str] = []

    def add(candidate: str) -> None:
        text = " ".join(candidate.split())
        if text and text not in queries:
            queries.append(text)

    for variant in negate(claim):
        add(variant)
    for outcome in competing_outcomes(claim):
        add(f"{' '.join(salient_terms(claim, 4))} {outcome}")
    for signal in signals:
        add(f"no {signal}")
    if not queries:
        add(f"evidence that contradicts: {claim}")
    return queries[:limit]
