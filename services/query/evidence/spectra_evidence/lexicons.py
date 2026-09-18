"""Configurable lexicons used by extractive summarisation and stance classification.

These are *data*, not logic: an operator can extend them without touching code,
and every consumer takes the lexicon as a parameter so a deployment can supply
its own domain vocabulary.  Nothing here encodes a universal truth - only how
enterprise records usually phrase the same fact.
"""

from __future__ import annotations

from collections.abc import Mapping

# attribute -> canonical value -> surface forms observed in real records/prose.
# Surfaces are matched case-insensitively on word boundaries.
ATTRIBUTE_LEXICON: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    "status": {
        "approved": ("approved", "approval granted", "authorised", "authorized", "accepted"),
        "rejected": ("rejected", "declined", "denied", "refused", "turned down"),
        "failed": ("failed", "failure", "did not complete", "unsuccessful"),
        "succeeded": ("succeeded", "successful", "success", "completed successfully"),
        "pending": ("pending", "awaiting approval", "in review", "under review"),
        "cancelled": ("cancelled", "canceled", "aborted"),
    },
    "outcome": {
        "timed_out": ("timed out", "timeout", "time-out", "timed-out"),
        "unavailable": ("unavailable", "was down", "outage", "unreachable", "not reachable"),
        "resolved": ("resolved", "mitigated", "remediated", "fixed"),
        "degraded": ("degraded", "partially available"),
    },
    # Lifecycle markers drive temporal-impossibility checks (see PRECEDENCE_RULES).
    "lifecycle": {
        "created": ("created", "opened", "submitted", "initiated", "raised", "logged"),
        "completed": ("completed", "closed", "finished", "settled"),
    },
}

# Attributes whose values are mutually exclusive: two different values for the
# same entity cannot both be true, which is what makes a value conflict real.
EXCLUSIVE_ATTRIBUTES: frozenset[str] = frozenset({"status", "outcome", "lifecycle"})

# Values that describe the SAME situation in different words.  Two sources are
# not contradicting each other when one says a service "timed out" and another
# says it was "unavailable" - a classifier that cries wolf on synonyms gets ignored.
COMPATIBLE_VALUES: Mapping[str, tuple[frozenset[str], ...]] = {
    "outcome": (frozenset({"timed_out", "unavailable", "degraded"}),),
    "status": (frozenset({"failed", "cancelled"}),),
}

# Numeric attributes compared with a relative tolerance rather than string equality.
NUMERIC_ATTRIBUTES: frozenset[str] = frozenset({"amount", "count", "total", "quantity"})

# Two numeric assertions within 0.5% are treated as the same figure (rounding and
# currency conversion noise), anything beyond that is a genuine disagreement.
NUMERIC_RELATIVE_TOLERANCE = 0.005

# Negation cues searched in the tokens immediately before a matched value.
NEGATION_CUES: frozenset[str] = frozenset(
    {
        "not",
        "never",
        "no",
        "nor",
        "without",
        "n't",
        "cannot",
        "failed",
        "denied",
        "neither",
        "isn't",
        "wasn't",
        "weren't",
        "hasn't",
        "hadn't",
        "doesn't",
        "didn't",
    }
)

# A negation binds to a value within four tokens ("was not fully approved"); any
# further away it usually negates a different clause.
NEGATION_WINDOW_TOKENS = 4

# (earlier, later) marker pairs as (attribute, value).  A record asserting the
# later marker BEFORE the earlier one is physically impossible for one entity.
PRECEDENCE_RULES: tuple[tuple[tuple[str, str], tuple[str, str]], ...] = (
    (("lifecycle", "created"), ("status", "failed")),
    (("lifecycle", "created"), ("status", "succeeded")),
    (("lifecycle", "created"), ("status", "approved")),
    (("lifecycle", "created"), ("status", "rejected")),
    (("lifecycle", "created"), ("lifecycle", "completed")),
    (("lifecycle", "created"), ("outcome", "resolved")),
    (("outcome", "unavailable"), ("outcome", "resolved")),
)

# Enterprise clocks drift; only gaps larger than this are treated as impossible
# rather than as skew between two systems.
TEMPORAL_TOLERANCE_SECONDS = 60.0

# Words that make a sentence worth quoting as an extractive summary.
INFORMATIVE_KEYWORDS: frozenset[str] = frozenset(
    {
        "because",
        "caused",
        "cause",
        "due",
        "error",
        "failed",
        "failure",
        "reason",
        "rejected",
        "approved",
        "status",
        "timeout",
        "timed",
        "unavailable",
        "exceeded",
        "declined",
        "incident",
        "root",
    }
)
