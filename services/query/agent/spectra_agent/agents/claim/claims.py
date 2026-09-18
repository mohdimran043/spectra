"""The claim builder: state what the retrieved evidence actually supports.

Claims are derived from the corpus, never invented for it.  Extractively, each
claim is a statement the evidence itself makes, taken from the highest-weight
items.  With a model available the same evidence is handed over and the model is
asked to state the findings it supports - and every proposal that does not share
enough content with the corpus is dropped, so the model can rephrase what was
retrieved but cannot introduce a cause the sources never mention.

Everything is grounded to the investigation's focal entity first: a claim about
TX83155 must come from evidence naming TX83155.  When nothing names it the full
set is used, so a corpus that simply lacks the answer ends in abstention on the
evidence rather than in having no claims at all.

Scoring lives in :mod:`.scoring`, and it scores each claim on its own evidence:
there is no normalisation across claims and no probability that must sum to one.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from spectra_config import Settings, get_settings
from spectra_config.logging import get_logger
from spectra_schemas import (
    Claim,
    ClaimStatus,
    EvidenceItem,
    EvidenceLedger,
    EvidenceStance,
    InvestigationState,
    ModelRole,
    claim_id,
)

from ...causal_lexicon import competing_outcomes, negate
from ...evidence_adapter import first_sentence
from ...grounding import focal_terms
from ...lexicons import content_tokens, token_overlap
from ...llm import structured, text_messages
from ...stance import classify
from ...sufficiency import names_subject
from ...thresholds import (
    LLM_GROUNDING_MIN_OVERLAP,
    MAX_CLAIMS,
    MIN_CLAIMS_DEEP,
    WEAK_LEADER_CONFIDENCE,
)
from .scoring import rationale_for, resolve, score_claim

log = get_logger(__name__)

# Two statements sharing this much of their content are the same finding said
# twice; keeping both would corroborate a claim with itself.
CLAIM_DEDUPE_OVERLAP = 0.7

# Claims are numbered only once the merged set is final; until then they carry
# this placeholder, which _renumber replaces with the contract id (C1, C2 ...).
UNNUMBERED = "C0"

# How many evidence excerpts the model is shown: enough context to state the
# findings, few enough that every one of them stays checkable.
MODEL_EVIDENCE_LIMIT = 12

CLAIM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "maxItems": MAX_CLAIMS,
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "rationale": {"type": "string"},
                    "disproof_probe": {"type": "string"},
                },
                "required": ["text", "rationale", "disproof_probe"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["claims"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You state the findings that an enterprise investigation's evidence supports. "
    "Use ONLY what the supplied evidence states - never a cause it does not mention. "
    "Each finding is one sentence, plus the evidence it rests on and one probe that "
    "would show it is wrong. Reply with JSON only."
)


class ClaimBuilder:
    """Builds, links, scores and ranks the claims an investigation asserts."""

    def __init__(self, settings: Settings | None = None, gateway: Any | None = None) -> None:
        self._settings = settings or get_settings()
        self._gateway = gateway

    # -- building ---------------------------------------------------------
    async def build(
        self,
        state: InvestigationState,
        evidence: Sequence[EvidenceItem],
        *,
        allow_llm: bool = True,
    ) -> list[Claim]:
        """The statements ``evidence`` supports, grounded to the focal entity."""
        if not evidence:
            return []
        grounded = _grounded_to_subject(evidence, state)
        subject = _subject(state, grounded)
        extracted = _extract(grounded, subject)
        if not allow_llm or self._gateway is None:
            return _renumber(state, extracted[:MAX_CLAIMS])
        proposed = await self._ask_model(state, grounded, subject)
        return _renumber(state, _merge(extracted, proposed)[:MAX_CLAIMS])

    async def _ask_model(
        self, state: InvestigationState, items: Sequence[EvidenceItem], subject: str
    ) -> list[Claim]:
        corpus = "\n".join(
            f"[E{index + 1}] {item.summary} :: {item.excerpt}"
            for index, item in enumerate(items[:MODEL_EVIDENCE_LIMIT])
        )
        outcome = await structured(
            self._gateway,
            messages=text_messages(
                SYSTEM_PROMPT,
                f"Investigation goal: {state.goal}\nSubject: {subject}\nEvidence:\n{corpus}",
            ),
            schema=CLAIM_SCHEMA,
            role=ModelRole.DEEP_BRAIN,
            max_tokens=1024,
        )
        if not outcome.ok or outcome.data is None:
            log.info("claims.extractive_only", reason=outcome.reason)
            return []
        corpus_tokens = content_tokens(" ".join(f"{i.summary} {i.excerpt}" for i in items))
        built: list[Claim] = []
        for raw in outcome.data.get("claims") or []:
            claim = _from_model(raw, items, subject, corpus_tokens)
            if claim is not None:
                built.append(claim)
        return built

    # -- linking, scoring, ranking ----------------------------------------
    def attach(self, claims: Sequence[Claim], items: Sequence[EvidenceItem]) -> list[Claim]:
        """Link evidence to the claims it speaks to - returns NEW claims."""
        return [_linked(claim, items) for claim in claims]

    def score(self, claim: Claim, ledger: EvidenceLedger) -> Claim:
        """Confidence and status from this claim's own evidence - a NEW claim."""
        scored = score_claim(claim, ledger)
        support, contra = resolve(scored, ledger)
        return scored.model_copy(update={"rationale": rationale_for(claim, support, contra)})

    def rank(self, claims: Sequence[Claim]) -> list[Claim]:
        """Best-supported first; ids stay attached to their claim."""
        return sorted(
            claims,
            key=lambda claim: (claim.confidence, len(claim.supporting_evidence)),
            reverse=True,
        )

    def should_build_more(self, state: InvestigationState) -> bool:
        """True while the claim set cannot yet carry an answer."""
        live = [c for c in state.claims if c.status is not ClaimStatus.REFUTED]
        if not live or len(live) < MIN_CLAIMS_DEEP:
            return True
        leader = max(live, key=lambda claim: claim.confidence)
        if leader.status in (ClaimStatus.CONTRADICTED, ClaimStatus.INSUFFICIENT):
            return True
        return leader.confidence < WEAK_LEADER_CONFIDENCE


# -- generation helpers ---------------------------------------------------
def _extract(items: Sequence[EvidenceItem], subject: str) -> list[Claim]:
    """One claim per distinct statement, strongest evidence first."""
    claims: list[Claim] = []
    seen: list[frozenset[str]] = []
    for item in sorted(items, key=lambda i: i.weight, reverse=True):
        if len(claims) >= MAX_CLAIMS:
            break
        text = _statement(item, subject)
        if text is None:
            continue
        key = frozenset(content_tokens(text))
        if not key or _is_duplicate(key, seen):
            continue
        seen.append(key)
        claims.append(
            Claim(
                claim_id=UNNUMBERED,
                text=text,
                supporting_evidence=[item.evidence_id],
                disproof_probe=_probe(text, subject),
                rationale=f"Stated by {item.citation()}",
            )
        )
    return claims


def _from_model(
    raw: Any, items: Sequence[EvidenceItem], subject: str, corpus_tokens: set[str]
) -> Claim | None:
    """A model proposal, kept only when the corpus actually says it."""
    if not isinstance(raw, dict) or not isinstance(raw.get("text"), str):
        return None
    text = " ".join(raw["text"].split()).strip()
    if not text:
        return None
    overlap = content_tokens(text) & corpus_tokens
    if len(overlap) < LLM_GROUNDING_MIN_OVERLAP:
        log.info("claims.ungrounded_dropped", text=text[:80])
        return None
    supporting = [item for item in items if classify(text, item) is EvidenceStance.SUPPORTING]
    return Claim(
        claim_id=UNNUMBERED,
        text=text,
        supporting_evidence=[item.evidence_id for item in supporting],
        disproof_probe=str(raw.get("disproof_probe") or "").strip() or _probe(text, subject),
        rationale=str(raw.get("rationale") or "")[:600],
    )


def _merge(extracted: Sequence[Claim], proposed: Sequence[Claim]) -> list[Claim]:
    """Add model proposals that are not already stated extractively."""
    merged = list(extracted)
    seen = [frozenset(content_tokens(claim.text)) for claim in merged]
    for claim in proposed:
        key = frozenset(content_tokens(claim.text))
        if not key or _is_duplicate(key, seen):
            continue
        seen.append(key)
        merged.append(claim)
    return merged


def _renumber(state: InvestigationState, claims: Sequence[Claim]) -> list[Claim]:
    return [
        claim.model_copy(update={"claim_id": claim_id(state.investigation_id, index)})
        for index, claim in enumerate(claims)
    ]


def _is_duplicate(key: frozenset[str], seen: Sequence[frozenset[str]]) -> bool:
    return any(token_overlap(key, other) >= CLAIM_DEDUPE_OVERLAP for other in seen)


# -- text helpers ---------------------------------------------------------
# A claim has to read as an assertion. Serialised database rows and extracted
# tables are excellent *evidence* but terrible *statements*: their first
# "sentence" is a column header, which would surface as
# "TX83155: | transaction_id | customer_id | amount | ...".
MIN_STATEMENT_WORDS = 4
MAX_PIPES_FOR_PROSE = 1
MIN_ALPHA_RATIO = 0.6


def _reads_as_prose(text: str) -> bool:
    """Reject table rows, delimiter runs and key/value dumps."""
    stripped = text.strip()
    if len(stripped.split()) < MIN_STATEMENT_WORDS:
        return False
    if stripped.count("|") > MAX_PIPES_FOR_PROSE:
        return False
    if set(stripped) <= set("-=_| \t"):
        return False
    letters = sum(ch.isalpha() or ch.isspace() for ch in stripped)
    return letters / len(stripped) >= MIN_ALPHA_RATIO


def _prose_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", (text or "").replace("\n", " "))
    return [p.strip() for p in parts if _reads_as_prose(p)]


def _statement(item: EvidenceItem, subject: str) -> str | None:
    """The evidence's own words as one assertion, or None if it has none.

    Returning None is deliberate: an item that carries no prose still counts as
    evidence for another claim, it just cannot be the claim itself.
    """
    candidate = first_sentence(item.summary or item.excerpt).strip().rstrip("…").strip()
    if not _reads_as_prose(candidate):
        candidate = next(iter(_prose_sentences(f"{item.summary} {item.excerpt}")), "")
    candidate = candidate.strip().rstrip("…").rstrip(".").strip()
    if not candidate or not _reads_as_prose(candidate):
        return None
    if subject and subject.lower() not in candidate.lower():
        candidate = f"{subject}: {candidate}"
    return f"{candidate}."


def _probe(text: str, subject: str) -> str:
    """What would have to be found for this claim to be wrong."""
    outcome = next(iter(competing_outcomes(text)), None)
    if outcome:
        return f"Evidence that {subject} shows {outcome} instead."
    variant = next(iter(negate(text)), None)
    if variant:
        return f"Evidence that {variant.rstrip('.')}."
    return f"Evidence that contradicts: {text}"


def _subject(state: InvestigationState, items: Sequence[EvidenceItem]) -> str:
    understanding = state.understanding
    if understanding and understanding.detected_ids:
        return ", ".join(understanding.detected_ids[:2])
    entities = [entity for item in items for entity in item.entities]
    if entities:
        return entities[0]
    return "The reported outcome"


# -- grounding ------------------------------------------------------------
def _grounded_to_subject(
    items: Sequence[EvidenceItem], state: InvestigationState
) -> Sequence[EvidenceItem]:
    """Keep only evidence that actually concerns the focal entity.

    A claim about why TX82931 failed must rest on evidence that mentions
    TX82931.  Without this gate, generic retrieved text - a handbook page that
    merely says "no incidents were recorded" - becomes a plausible-sounding but
    unfounded finding, and because such pages are numerous they then outweigh
    the one page that names the transaction.
    """
    focal = focal_terms(state)
    if not focal:
        return items
    grounded = [item for item in items if names_subject(item, focal)]
    if not grounded:
        log.info("claims.no_grounded_evidence", focal=focal[:3], considered=len(items))
        return items
    if len(grounded) < len(items):
        log.info(
            "claims.grounded_to_subject",
            focal=focal[:3],
            kept=len(grounded),
            discarded=len(items) - len(grounded),
        )
    return grounded


# -- linking --------------------------------------------------------------
def _linked(claim: Claim, items: Sequence[EvidenceItem]) -> Claim:
    support = list(claim.supporting_evidence)
    contra = list(claim.contradicting_evidence)
    for item in items:
        stance = _stance_for(claim, item)
        if stance is EvidenceStance.SUPPORTING and item.evidence_id not in support:
            support.append(item.evidence_id)
        elif stance is EvidenceStance.CONTRADICTING and item.evidence_id not in contra:
            contra.append(item.evidence_id)
    contested = set(contra)
    return claim.model_copy(
        update={
            "supporting_evidence": [i for i in support if i not in contested],
            "contradicting_evidence": contra,
        }
    )


def _stance_for(claim: Claim, item: EvidenceItem) -> EvidenceStance:
    """Stance is relative to a claim, so it is read per claim, not per item.

    The one exception is evidence the disproof probe already judged against this
    exact claim: that verdict is kept rather than recomputed.
    """
    if claim.claim_id in item.claim_ids:
        return item.stance
    return classify(claim.text, item)


__all__ = ["CLAIM_SCHEMA", "ClaimBuilder"]
