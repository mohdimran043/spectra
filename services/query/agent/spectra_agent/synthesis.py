"""Answer synthesis under the grounding law.

With a model available the evidence excerpts - and nothing else - are given to
it, inline ``[E1]`` citations are required, and every citation is verified
afterwards: unsupported sentences are dropped, not published.  Without a model
the answer is assembled extractively from the leading claim and the
highest-weight evidence.  When sufficiency is below threshold the answer is an
explicit abstention that still reports what *was* found and what is missing.

Synthesis writes prose, nothing else: the claims themselves are built and scored
before it runs, and it reads the leading one rather than inventing its own.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from spectra_config import Settings, get_settings
from spectra_config.logging import get_logger
from spectra_schemas import (
    Claim,
    ClaimStatus,
    EvidenceItem,
    InvestigationState,
    ModelRole,
)

from . import sufficiency
from .grounding import labels_for, split_sentences, unsupported_sentences
from .llm import structured, text_messages
from .thresholds import ANSWER_MAX_SENTENCES

log = get_logger(__name__)

ABSTENTION_TEXT = (
    "Insufficient evidence. I found related information but cannot establish the "
    "requested conclusion with sufficient support."
)

ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You write the answer to an enterprise investigation using ONLY the numbered evidence "
    "excerpts supplied. Every sentence must end with the citation(s) it comes from, like [E1] "
    "or [E2][E3]. Never state anything the excerpts do not state. Reply with JSON only."
)

# How many evidence items are offered to the answer; more than this and the
# citations stop being checkable by a human reader.
ANSWER_EVIDENCE_LIMIT = 8


class AnswerSynthesiser:
    """Turns an investigation state into a cited answer."""

    def __init__(self, settings: Settings | None = None, gateway: Any | None = None) -> None:
        self._settings = settings or get_settings()
        self._gateway = gateway

    async def compose(self, state: InvestigationState, *, allow_llm: bool = True) -> str:
        """The cited answer, or an explicit abstention when nothing supports one."""
        items = sorted(state.evidence.items, key=lambda i: i.weight, reverse=True)[:ANSWER_EVIDENCE_LIMIT]
        score = sufficiency.compute(state.evidence)
        threshold = self._settings.sufficiency_threshold
        intent = state.understanding.intent if state.understanding else None
        authoritative = sufficiency.authoritative_item(state.evidence, intent)
        if not items or (score < threshold and authoritative is None):
            return self._abstain(state, items, score, threshold)

        labels = labels_for([item.evidence_id for item in items])
        text = ""
        if allow_llm and self._gateway is not None:
            text = await self._generate(state, items, labels)
        if not text:
            text = self._extractive(state, items, labels)
        if not text.strip():
            return self._abstain(state, items, score, threshold)
        return text

    # -- abstention -------------------------------------------------------
    def _abstain(
        self,
        state: InvestigationState,
        items: Sequence[EvidenceItem],
        score: float,
        threshold: float,
    ) -> str:
        lines = [ABSTENTION_TEXT, "", "What I found:"]
        if items:
            lines.extend(f"- {_statement(item)} [E{index + 1}]" for index, item in enumerate(items))
        else:
            lines.append("- Not found: no evidence cleared the relevance floor for this question.")
        lines.extend(["", "What is missing:"])
        missing = sufficiency.gaps(state.evidence) or [
            f"sufficiency {score:.2f} is below the {threshold:.2f} threshold required to assert a conclusion"
        ]
        lines.extend(f"- Missing: {gap}" for gap in missing)
        log.info(
            "synthesis.abstained",
            investigation_id=state.investigation_id,
            sufficiency=score,
            threshold=threshold,
        )
        return "\n".join(lines)

    # -- generative -------------------------------------------------------
    async def _generate(
        self, state: InvestigationState, items: Sequence[EvidenceItem], labels: dict[str, str]
    ) -> str:
        excerpts = "\n".join(
            f"[E{index + 1}] {item.summary} :: {item.excerpt} (source: {item.citation()})"
            for index, item in enumerate(items)
        )
        outcome = await structured(
            self._gateway,
            messages=text_messages(
                SYSTEM_PROMPT, f"Question: {state.goal}\nEvidence:\n{excerpts}"
            ),
            schema=ANSWER_SCHEMA,
            role=ModelRole.DEEP_BRAIN,
            max_tokens=768,
        )
        if not outcome.ok or outcome.data is None:
            log.info("synthesis.extractive_fallback", reason=outcome.reason)
            return ""
        raw = str(outcome.data.get("answer") or "").strip()
        return _drop_unsupported(raw, labels)

    # -- extractive -------------------------------------------------------
    def _extractive(
        self, state: InvestigationState, items: Sequence[EvidenceItem], labels: dict[str, str]
    ) -> str:
        index_of = {item.evidence_id: f"[E{i + 1}]" for i, item in enumerate(items)}
        sentences: list[str] = []
        leader = state.leading_claim()
        if leader is not None and leader.status in (ClaimStatus.SUPPORTED, ClaimStatus.WEAK):
            citations = "".join(index_of[e] for e in leader.supporting_evidence if e in index_of)
            if citations:
                sentences.append(f"{leader.text.rstrip('.')}{_qualifier(leader)} {citations}.")
        for item in items:
            if len(sentences) >= ANSWER_MAX_SENTENCES:
                break
            sentences.append(f"{_statement(item)} {index_of[item.evidence_id]}.")
        for contradiction in state.contradictions[:1]:
            pair = "".join(
                index_of[e] for e in (contradiction.evidence_a, contradiction.evidence_b) if e in index_of
            )
            if pair:
                sentences.append(f"Sources disagree: {contradiction.statement.rstrip('.')} {pair}.")
        text = " ".join(sentences)
        return _drop_unsupported(text, labels)


def _qualifier(leader: Claim) -> str:
    """Never state a contested or weak claim as if it were settled."""
    if leader.contradicting_evidence:
        return " (contested by conflicting evidence)"
    if leader.status is not ClaimStatus.SUPPORTED:
        return " (weakly supported)"
    return ""


def _statement(item: EvidenceItem) -> str:
    """The evidence's own words, trimmed to a whole clause."""
    text = item.summary.strip()
    if text.endswith("…"):
        text = text[:-1].rstrip().rsplit(" ", 1)[0] + " …"
    return text.rstrip(".")


def _drop_unsupported(text: str, labels: dict[str, str]) -> str:
    """Remove any sentence that asserts something without a valid citation."""
    if not text:
        return ""
    unsupported = set(unsupported_sentences(text, labels))
    if not unsupported:
        return text
    kept = [s for s in split_sentences(text) if s not in unsupported]
    log.info("synthesis.sentences_dropped", dropped=len(unsupported), kept=len(kept))
    return " ".join(kept)
