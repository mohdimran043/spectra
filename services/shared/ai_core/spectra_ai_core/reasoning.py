"""Strip model reasoning traces before anything downstream can see them.

Reasoning models (Qwen3, DeepSeek-R1, QwQ and friends) emit an internal
monologue wrapped in ``<think>`` - or ``<reasoning>`` / ``<scratchpad>`` -
blocks.  SPECTRA's product contract forbids exposing model chain-of-thought:
the UI shows *action summaries*, evidence and decisions, never the model's
private reasoning.

Stripping happens here, at the provider boundary, so no consumer - synthesis,
the API, the trace stream or the UI - can leak it by forgetting to.
"""

from __future__ import annotations

import re

# Paired tags a reasoning model may wrap its monologue in.
REASONING_TAGS: tuple[str, ...] = ("think", "thinking", "reasoning", "scratchpad", "reflection")

_PAIRED = re.compile(
    r"<(?P<tag>" + "|".join(REASONING_TAGS) + r")\b[^>]*>.*?</(?P=tag)\s*>",
    re.DOTALL | re.IGNORECASE,
)
# An unterminated opening tag means the model was cut off mid-monologue; drop
# everything from it onward rather than shipping half a thought to the user.
_UNCLOSED = re.compile(
    r"<(?:" + "|".join(REASONING_TAGS) + r")\b[^>]*>.*\Z",
    re.DOTALL | re.IGNORECASE,
)
# A stray closing tag with no opener: everything before it was the monologue.
_LEADING_CLOSE = re.compile(
    r"\A.*?</(?:" + "|".join(REASONING_TAGS) + r")\s*>",
    re.DOTALL | re.IGNORECASE,
)


def strip_reasoning(text: str) -> tuple[str, bool]:
    """Return ``(visible_text, had_reasoning)``.

    ``had_reasoning`` lets callers record *that* the model reasoned - useful
    telemetry - without retaining *what* it reasoned.
    """
    if not text:
        return "", False

    cleaned = _PAIRED.sub("", text)
    if _LEADING_CLOSE.search(cleaned):
        cleaned = _LEADING_CLOSE.sub("", cleaned)
    cleaned = _UNCLOSED.sub("", cleaned)

    stripped = cleaned.strip()
    had_reasoning = stripped != text.strip()

    # If the model produced *only* a monologue there is no answer to show.
    # Returning the monologue would violate the contract, so return nothing and
    # let the caller treat it as an empty generation.
    return stripped, had_reasoning
