"""Claim Builder - the statements the investigation is prepared to assert.

A cognition agent, not a retrieval one: it exposes no tool.  It reads the
evidence gathered so far and states what that evidence supports, grounded to the
investigation's focal entity, then scores each statement on its own evidence -
supporting weight, independent sources, diversity, minus what contradicts it.

Nothing here is normalised across claims.  Two findings do not share one
probability mass, so a well-corroborated conclusion keeps a high confidence
instead of having it divided among the alternatives it happens to be listed
beside.  The Brain then hands the leading claim to the Disproof Agent, which
tries to break it.

Switched off with the ``claim`` deployment flag.
"""

from __future__ import annotations

from .claims import CLAIM_SCHEMA, ClaimBuilder
from .scoring import confidence_for, rationale_for, resolve, score_claim, status_for

__all__ = [
    "CLAIM_SCHEMA",
    "ClaimBuilder",
    "confidence_for",
    "rationale_for",
    "resolve",
    "score_claim",
    "status_for",
]
