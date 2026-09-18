"""LLM verification for genuinely ambiguous resolutions.

This step exists because the cheap signals sometimes *tie*: two customers whose
names differ by one character, or an id that two grammars could both claim.  The
model is asked one narrow question with a strict JSON schema and a closed list of
candidate ids; it can always answer ``null``.

If the gateway is degraded the resolver must NOT guess - it returns
``needs_verification=True`` and the UI asks a human.  That is the whole point of
the degraded-mode contract.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from spectra_config.logging import get_logger
from spectra_schemas import ModelRole, ResolutionCandidate

log = get_logger(__name__)

#: A model verdict is evidence, not proof: it can never outrank an exact
#: canonical-key match (1.0) or a system-of-record lookup (0.97).
MAX_LLM_CONFIDENCE = 0.90

#: Token ceiling - the answer is one id plus one sentence.
VERIFICATION_MAX_TOKENS = 256
VERIFICATION_TEMPERATURE = 0.0

VERIFICATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "entity_id": {"type": ["string", "null"], "description": "Chosen candidate id, or null"},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "reason": {"type": "string"},
    },
    "required": ["entity_id", "confidence", "reason"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = (
    "You disambiguate enterprise entity references. Choose at most one candidate id from the list. "
    "If the evidence does not clearly identify one candidate, return null. Never invent an id."
)


@dataclass(frozen=True)
class VerificationOutcome:
    entity_id: str | None
    confidence: float
    reason: str
    degraded: bool


async def verify_candidates(
    gateway: Any,
    surface: str,
    entity_type: str,
    candidates: Sequence[ResolutionCandidate],
    *,
    context: str = "",
) -> VerificationOutcome:
    """Ask the model which candidate ``surface`` refers to."""
    if gateway is None or not candidates:
        return VerificationOutcome(None, 0.0, "verification unavailable: no gateway or candidates", True)
    if not gateway.role_available(ModelRole.DEEP_BRAIN):
        reasons = "; ".join(gateway.degraded_reasons()) or "deep_brain role unavailable"
        return VerificationOutcome(None, 0.0, f"verification unavailable: {reasons}", True)

    prompt = _build_prompt(surface, entity_type, candidates, context)
    try:
        result = await _generate(gateway, prompt)
    except Exception as exc:  # noqa: BLE001 - any provider failure degrades, never guesses
        log.warning("entity.verification_failed", surface=surface, error=str(exc))
        return VerificationOutcome(None, 0.0, f"verification failed: {exc}", True)

    if result.degraded:
        return VerificationOutcome(None, 0.0, f"verification degraded: {result.degraded_reason}", True)
    return _parse(result, candidates)


async def _generate(gateway: Any, prompt: str) -> Any:
    from spectra_ai_core.interfaces import ChatMessage

    messages = (ChatMessage(role="system", content=_SYSTEM_PROMPT), ChatMessage(role="user", content=prompt))
    return await gateway.generate(
        messages,
        role=ModelRole.DEEP_BRAIN,
        max_tokens=VERIFICATION_MAX_TOKENS,
        temperature=VERIFICATION_TEMPERATURE,
        json_schema=VERIFICATION_SCHEMA,
    )


def _build_prompt(surface: str, entity_type: str, candidates: Sequence[ResolutionCandidate], context: str) -> str:
    lines = [f"Mention: {surface!r}", f"Expected type: {entity_type}", "Candidates:"]
    lines.extend(
        f"- {candidate.entity_id}: {candidate.canonical_name} "
        f"(prior={candidate.score:.3f}, via {candidate.method})"
        for candidate in candidates
    )
    if context:
        lines.append(f"Surrounding text: {context}")
    lines.append("Answer with JSON matching the schema.")
    return "\n".join(lines)


def _parse(result: Any, candidates: Sequence[ResolutionCandidate]) -> VerificationOutcome:
    payload = result.structured if isinstance(result.structured, dict) else _loads(result.text)
    if not isinstance(payload, dict):
        return VerificationOutcome(None, 0.0, "verification returned unparseable output", True)
    chosen = payload.get("entity_id")
    allowed = {candidate.entity_id for candidate in candidates}
    if chosen is None or chosen not in allowed:
        return VerificationOutcome(None, 0.0, str(payload.get("reason") or "model declined to choose"), False)
    confidence = min(MAX_LLM_CONFIDENCE, max(0.0, float(payload.get("confidence") or 0.0)))
    return VerificationOutcome(str(chosen), confidence, str(payload.get("reason") or "model verdict"), False)


def _loads(text: str) -> Any:
    import json

    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None
