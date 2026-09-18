"""The hypothesis engine: generate competing explanations, then score them.

Generation is grounded: a cause only becomes a hypothesis when its vocabulary
actually occurs in the retrieved corpus.  With a model available the same
grounding rule is applied to the model's proposals, so the engine cannot
hallucinate a cause the corpus never mentions.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from spectra_config import Settings, get_settings
from spectra_config.logging import get_logger
from spectra_schemas import (
    EvidenceItem,
    EvidenceLedger,
    EvidenceStance,
    Hypothesis,
    HypothesisStatus,
    InvestigationState,
    ModelRole,
)

from ...lexicons import content_tokens
from ...llm import structured, text_messages
from ...thresholds import (
    CONTRADICTED_WEIGHT_RATIO,
    COUNT_DAMPING_FLOOR,
    DISPROOF_WEIGHT_RATIO,
    DIVERSITY_DAMPING_FLOOR,
    HYPOTHESIS_CONTRADICTED_MAX,
    HYPOTHESIS_SUPPORTED_MIN,
    LLM_GROUNDING_MIN_OVERLAP,
    MAX_HYPOTHESES,
    MIN_CONTRADICTING_FOR_DISPROOF,
    MIN_SUPPORTING_ITEMS,
    SUPPORT_DOMINANCE_RATIO,
    SUPPORT_SMOOTHING,
    WEAK_LEADER_CONFIDENCE,
)
from .causal_lexicon import mine_categories, mine_error_codes, salient_terms

log = get_logger(__name__)

# Priors: a cause mentioned by more of the corpus starts higher, but no
# deterministic prior may exceed 0.5 - the corpus mentioning something is not
# the corpus proving it.
MIN_PRIOR = 0.10
MAX_PRIOR = 0.50

HYPOTHESIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "hypotheses": {
            "type": "array",
            "maxItems": MAX_HYPOTHESES,
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "rationale": {"type": "string"},
                    "predicted_signals": {"type": "array", "items": {"type": "string"}},
                    "disproof_probe": {"type": "string"},
                },
                "required": ["description", "rationale", "predicted_signals", "disproof_probe"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["hypotheses"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You propose competing explanations for an enterprise investigation. "
    "Use ONLY causes that the supplied evidence mentions. For each hypothesis give the "
    "signals that must exist if it is true, and one probe that would prove it wrong. "
    "Reply with JSON only."
)


class HypothesisEngine:
    """Generates and scores competing explanations."""

    def __init__(self, settings: Settings | None = None, gateway: Any | None = None) -> None:
        self._settings = settings or get_settings()
        self._gateway = gateway

    # -- generation -------------------------------------------------------
    async def generate(
        self,
        state: InvestigationState,
        context_evidence: Sequence[EvidenceItem],
        *,
        allow_llm: bool = True,
    ) -> list[Hypothesis]:
        """Competing explanations mined from ``context_evidence``."""
        if not context_evidence:
            return []
        subject = _subject(state, context_evidence)
        grounded = _about_subject(context_evidence, state)
        deterministic = self._mine(state, grounded, subject)
        if not allow_llm or self._gateway is None:
            return deterministic[:MAX_HYPOTHESES]
        proposed = await self._ask_model(state, grounded, subject)
        merged = _merge(deterministic, proposed)
        return _renumber(merged[:MAX_HYPOTHESES])

    def _mine(
        self, state: InvestigationState, items: Sequence[EvidenceItem], subject: str
    ) -> list[Hypothesis]:
        texts = [f"{item.summary} {item.excerpt}" for item in items]
        candidates: list[Hypothesis] = []
        for category, terms in mine_categories(texts):
            matched = [i for i in items if any(t in f"{i.summary} {i.excerpt}".lower() for t in terms)]
            candidates.append(
                Hypothesis(
                    hypothesis_id=f"H{len(candidates) + 1}",
                    description=f"{subject} was caused by {category.label}.",
                    rationale=(
                        f"The term(s) {terms[:3]} appear in {len(matched)} retrieved item(s): "
                        f"{', '.join(i.citation() for i in matched[:3])}."
                    ),
                    prior=_prior(len(matched), len(items)),
                    supporting_evidence=[i.evidence_id for i in matched],
                    predicted_signals=[f"{signal} for {subject}" for signal in category.signals],
                    disproof_probe=(
                        f"Evidence that {category.counter_terms[0]} for {subject}, "
                        f"i.e. that {category.label} did not occur."
                    ),
                )
            )
        for code in mine_error_codes(texts):
            matched = [i for i in items if code in f"{i.summary} {i.excerpt}"]
            candidates.append(
                Hypothesis(
                    hypothesis_id=f"H{len(candidates) + 1}",
                    description=f"{subject} is explained by error code {code} recorded in the sources.",
                    rationale=f"Code {code} appears literally in {len(matched)} retrieved item(s).",
                    prior=_prior(len(matched), len(items)),
                    supporting_evidence=[i.evidence_id for i in matched],
                    predicted_signals=[
                        f"another occurrence of {code} in the same window",
                        f"a definition or runbook entry for {code}",
                    ],
                    disproof_probe=f"Records for {subject} in the same window that do not carry {code}.",
                )
            )
        ordered = sorted(candidates, key=lambda h: (len(h.supporting_evidence), h.prior), reverse=True)
        return _renumber(ordered)

    async def _ask_model(
        self, state: InvestigationState, items: Sequence[EvidenceItem], subject: str
    ) -> list[Hypothesis]:
        corpus = "\n".join(
            f"[E{index + 1}] {item.summary} :: {item.excerpt}" for index, item in enumerate(items[:12])
        )
        outcome = await structured(
            self._gateway,
            messages=text_messages(
                SYSTEM_PROMPT,
                f"Investigation goal: {state.goal}\nSubject: {subject}\nEvidence:\n{corpus}",
            ),
            schema=HYPOTHESIS_SCHEMA,
            role=ModelRole.DEEP_BRAIN,
            max_tokens=1024,
        )
        if not outcome.ok or outcome.data is None:
            log.info("hypotheses.deterministic_only", reason=outcome.reason)
            return []
        corpus_tokens = content_tokens(" ".join(f"{i.summary} {i.excerpt}" for i in items))
        grounded: list[Hypothesis] = []
        for index, raw in enumerate(outcome.data.get("hypotheses") or []):
            hypothesis = _from_model(raw, index, items, corpus_tokens)
            if hypothesis is not None:
                grounded.append(hypothesis)
        return grounded

    # -- scoring ----------------------------------------------------------
    def score(self, hypothesis: Hypothesis, ledger: EvidenceLedger) -> Hypothesis:
        """Bayesian-flavoured update; returns a NEW hypothesis."""
        support_ids, contra_ids = _linked_ids(hypothesis, ledger)
        by_id = {item.evidence_id: item for item in ledger.items}
        support = [by_id[i] for i in support_ids if i in by_id]
        contra = [by_id[i] for i in contra_ids if i in by_id]
        support_weight = sum(item.weight for item in support)
        contra_weight = sum(item.weight for item in contra)

        if not support and not contra:
            return hypothesis.model_copy(
                update={
                    "confidence": round(hypothesis.prior * COUNT_DAMPING_FLOOR, 4),
                    "status": HypothesisStatus.INSUFFICIENT,
                    "supporting_evidence": support_ids,
                    "contradicting_evidence": contra_ids,
                }
            )

        prior = min(max(hypothesis.prior, 0.01), 0.99)
        prior_odds = prior / (1 - prior)
        likelihood_ratio = (SUPPORT_SMOOTHING + support_weight) / (SUPPORT_SMOOTHING + contra_weight)
        posterior_odds = prior_odds * likelihood_ratio
        raw = posterior_odds / (1 + posterior_odds)

        diversity_damping = DIVERSITY_DAMPING_FLOOR + (1 - DIVERSITY_DAMPING_FLOOR) * ledger.diversity()
        count_ratio = min(len(support) / MIN_SUPPORTING_ITEMS, 1.0)
        count_damping = COUNT_DAMPING_FLOOR + (1 - COUNT_DAMPING_FLOOR) * count_ratio
        confidence = round(max(0.0, min(1.0, raw * diversity_damping * count_damping)), 4)

        return hypothesis.model_copy(
            update={
                "confidence": confidence,
                "status": _status(confidence, support_weight, contra_weight, len(support), len(contra)),
                "supporting_evidence": support_ids,
                "contradicting_evidence": contra_ids,
            }
        )

    def rank(self, hypotheses: Sequence[Hypothesis]) -> list[Hypothesis]:
        return sorted(
            hypotheses,
            key=lambda h: (h.confidence, len(h.supporting_evidence)),
            reverse=True,
        )

    def normalise_confidences(self, hypotheses: Sequence[Hypothesis]) -> list[Hypothesis]:
        """Competing explanations share one probability mass; scale if they exceed it.

        Only the displayed confidence is rescaled - ``status`` stays as scored,
        because it reflects the balance of evidence for that one hypothesis, not
        its share of the field.
        """
        live = [h for h in hypotheses if h.status is not HypothesisStatus.DISPROVED]
        total = sum(h.confidence for h in live)
        if total <= 1.0 or total == 0:
            return list(hypotheses)
        return [
            h.model_copy(update={"confidence": round(h.confidence / total, 4)})
            if h.status is not HypothesisStatus.DISPROVED
            else h
            for h in hypotheses
        ]

    def should_generate_more(self, state: InvestigationState) -> bool:
        """True when the current explanation set cannot carry an answer."""
        live = [h for h in state.hypotheses if h.status is not HypothesisStatus.DISPROVED]
        if not live:
            return True
        leader = max(live, key=lambda h: h.confidence)
        if leader.status in (HypothesisStatus.CONTRADICTED, HypothesisStatus.DISPROVED):
            return True
        if all(h.status in (HypothesisStatus.WEAK, HypothesisStatus.INSUFFICIENT) for h in live):
            return True
        return leader.confidence < WEAK_LEADER_CONFIDENCE

    def attach(
        self, hypotheses: Sequence[Hypothesis], items: Sequence[EvidenceItem]
    ) -> list[Hypothesis]:
        """Link new evidence to the hypotheses it speaks to - returns NEW objects."""
        updated: list[Hypothesis] = []
        for hypothesis in hypotheses:
            terms = salient_terms(hypothesis.description)
            support = list(hypothesis.supporting_evidence)
            contra = list(hypothesis.contradicting_evidence)
            for item in items:
                text = f"{item.summary} {item.excerpt}".lower()
                if not any(term in text for term in terms):
                    continue
                bucket = contra if item.stance is EvidenceStance.CONTRADICTING else support
                if item.stance is EvidenceStance.NEUTRAL:
                    continue
                if item.evidence_id not in bucket:
                    bucket.append(item.evidence_id)
            updated.append(
                hypothesis.model_copy(
                    update={"supporting_evidence": support, "contradicting_evidence": contra}
                )
            )
        return updated


# -- helpers --------------------------------------------------------------
def _prior(matched: int, total: int) -> float:
    if total <= 0:
        return MIN_PRIOR
    share = matched / total
    return round(min(MAX_PRIOR, max(MIN_PRIOR, share)), 4)


def focal_terms(state: InvestigationState) -> list[str]:
    """The identifiers this investigation is actually about."""
    terms: list[str] = []
    understanding = state.understanding
    if understanding:
        terms.extend(understanding.detected_ids)
    terms.extend(state.entities)
    return [t.strip().lower() for t in terms if t and str(t).strip()]


def _about_subject(
    items: Sequence[EvidenceItem], state: InvestigationState
) -> Sequence[EvidenceItem]:
    """Keep only evidence that actually concerns the focal entity.

    A hypothesis about why TX82931 failed must be grounded in evidence that
    mentions TX82931.  Without this gate, generic retrieved text - a handbook
    page that merely says "no incidents were recorded" - seeds a plausible-
    sounding but unfounded explanation, and because such pages are numerous they
    then out-weigh the one page that names the transaction.

    When nothing names the subject the full set is returned unchanged: that case
    should end in abstention on the evidence, not in having no hypotheses at all.
    """
    focal = focal_terms(state)
    if not focal:
        return items
    grounded = [
        item
        for item in items
        if any(
            term in f"{item.summary} {item.excerpt} {' '.join(item.entities)}".lower()
            for term in focal
        )
    ]
    if not grounded:
        log.info("hypotheses.no_grounded_evidence", focal=focal[:3], considered=len(items))
        return items
    if len(grounded) < len(items):
        log.info(
            "hypotheses.grounded_to_subject",
            focal=focal[:3],
            kept=len(grounded),
            discarded=len(items) - len(grounded),
        )
    return grounded


def _subject(state: InvestigationState, items: Sequence[EvidenceItem]) -> str:
    understanding = state.understanding
    if understanding and understanding.detected_ids:
        return ", ".join(understanding.detected_ids[:2])
    entities = [entity for item in items for entity in item.entities]
    if entities:
        return entities[0]
    return "The reported outcome"


def _status(
    posterior: float, support_weight: float, contra_weight: float, support_count: int, contra_count: int
) -> HypothesisStatus:
    """Status follows the balance of evidence, not the displayed share."""
    if support_count == 0 and contra_count == 0:
        return HypothesisStatus.INSUFFICIENT
    if (
        contra_count >= MIN_CONTRADICTING_FOR_DISPROOF
        and contra_weight >= DISPROOF_WEIGHT_RATIO * support_weight
    ):
        return HypothesisStatus.DISPROVED
    if contra_count and (
        contra_weight >= CONTRADICTED_WEIGHT_RATIO * support_weight
        or posterior < HYPOTHESIS_CONTRADICTED_MAX
    ):
        return HypothesisStatus.CONTRADICTED
    if (
        posterior >= HYPOTHESIS_SUPPORTED_MIN
        and support_count >= MIN_SUPPORTING_ITEMS
        and support_weight >= SUPPORT_DOMINANCE_RATIO * contra_weight
    ):
        return HypothesisStatus.SUPPORTED
    if support_count == 0:
        return HypothesisStatus.INSUFFICIENT
    return HypothesisStatus.WEAK


def _linked_ids(hypothesis: Hypothesis, ledger: EvidenceLedger) -> tuple[list[str], list[str]]:
    support = list(hypothesis.supporting_evidence)
    contra = list(hypothesis.contradicting_evidence)
    for item in ledger.items:
        if hypothesis.hypothesis_id not in item.hypothesis_ids:
            continue
        if item.stance is EvidenceStance.CONTRADICTING and item.evidence_id not in contra:
            contra.append(item.evidence_id)
        elif item.stance is EvidenceStance.SUPPORTING and item.evidence_id not in support:
            support.append(item.evidence_id)
    contra_set = set(contra)
    return [i for i in support if i not in contra_set], contra


def _from_model(
    raw: Any, index: int, items: Sequence[EvidenceItem], corpus_tokens: set[str]
) -> Hypothesis | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("description"), str):
        return None
    description = raw["description"].strip()
    overlap = content_tokens(description) & corpus_tokens
    if len(overlap) < LLM_GROUNDING_MIN_OVERLAP:
        log.info("hypotheses.ungrounded_dropped", description=description[:80])
        return None
    terms = salient_terms(description)
    matched = [i for i in items if any(t in f"{i.summary} {i.excerpt}".lower() for t in terms)]
    signals = [s for s in raw.get("predicted_signals") or [] if isinstance(s, str)]
    return Hypothesis(
        hypothesis_id=f"M{index + 1}",
        description=description,
        rationale=str(raw.get("rationale") or "")[:600],
        prior=_prior(len(matched), len(items)),
        supporting_evidence=[i.evidence_id for i in matched],
        predicted_signals=signals[:5],
        disproof_probe=str(raw.get("disproof_probe") or "").strip() or None,
    )


def _merge(deterministic: Sequence[Hypothesis], proposed: Sequence[Hypothesis]) -> list[Hypothesis]:
    merged = list(deterministic)
    seen = {_key(h) for h in merged}
    for hypothesis in proposed:
        if _key(hypothesis) in seen:
            continue
        seen.add(_key(hypothesis))
        merged.append(hypothesis)
    return merged


def _key(hypothesis: Hypothesis) -> frozenset[str]:
    return frozenset(content_tokens(hypothesis.description))


def _renumber(hypotheses: Sequence[Hypothesis]) -> list[Hypothesis]:
    return [
        hypothesis.model_copy(update={"hypothesis_id": f"H{index + 1}"})
        for index, hypothesis in enumerate(hypotheses)
    ]
