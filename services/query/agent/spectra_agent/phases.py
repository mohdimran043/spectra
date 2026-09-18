"""The reasoning phases: hypothesise, attack, reconcile, verify.

These are separated from the retrieval loop because they answer a different
question.  Retrieval asks "what else is there?"; these ask "does what we have
actually support the conclusion?" - including the disproof phase, whose whole
purpose is to try to knock the leading explanation down.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from time import perf_counter

from spectra_config import Settings
from spectra_config.logging import get_logger
from spectra_schemas import (
    AgentName,
    EvidenceItem,
    Hypothesis,
    InvestigationState,
    TraceStatus,
)

from . import observation, state_ops
from .agents.disproof import DisproofAgent
from .agents.hypothesis import HypothesisEngine
from .agents.verifier import Verifier
from .lexicons import content_tokens
from .run_context import Run
from .tracing import Tracer

log = get_logger(__name__)


class ReasoningPhases:
    """Hypothesis scoring, disproof, contradiction sweep and verification."""

    def __init__(
        self,
        *,
        settings: Settings,
        flags: Mapping[str, bool],
        hypotheses: HypothesisEngine,
        verifier: Verifier,
        tracer: Tracer,
        disproof: DisproofAgent | None = None,
    ) -> None:
        self._settings = settings
        self._flags = dict(flags)
        self._hypotheses = hypotheses
        self._verifier = verifier
        self._tracer = tracer
        self._disproof = disproof

    # -- hypotheses -------------------------------------------------------
    async def reason(self, state: InvestigationState) -> InvestigationState:
        """Generate (when needed), link and score the competing explanations."""
        if not self._flags.get("hypothesis", True):
            return await self._tracer.step(
                state,
                AgentName.HYPOTHESIS,
                title="Hypothesis engine disabled",
                status=TraceStatus.SKIPPED,
                output_summary="competing explanations were not generated; evidence is reported as retrieved",
            )
        started = perf_counter()
        hypotheses = list(state.hypotheses)
        if not hypotheses or self._hypotheses.should_generate_more(state):
            generated = await self._hypotheses.generate(state, state.evidence.items)
            hypotheses = merge_hypotheses(hypotheses, generated)
        hypotheses = self._hypotheses.attach(hypotheses, state.evidence.items)
        state = self._rescore(state, hypotheses)
        state = state_ops.with_stage_latency(state, "hypotheses", _ms(started))
        leader = state.leading_hypothesis()
        return await self._tracer.step(
            state,
            AgentName.HYPOTHESIS,
            title=f"Scored {len(state.hypotheses)} competing hypothesis(es)",
            output_summary=(
                f"leading: {leader.hypothesis_id} {leader.description} "
                f"({leader.status.value}, {leader.confidence:.2f})"
                if leader
                else "no explanation could be mined from the retrieved evidence"
            ),
        )

    def _rescore(self, state: InvestigationState, hypotheses: Sequence[Hypothesis]) -> InvestigationState:
        scored = [self._hypotheses.score(h, state.evidence) for h in hypotheses]
        ranked = self._hypotheses.normalise_confidences(self._hypotheses.rank(scored))
        return state_ops.touch(state, hypotheses=ranked)

    # -- disproof ---------------------------------------------------------
    async def disproof(self, run: Run) -> InvestigationState:
        """Attack the leading explanation; 'nothing found' is a recorded result."""
        state = run.state
        leader = state.leading_hypothesis()
        if leader is None:
            return state
        if not self._flags.get("disproof", True):
            run.state = await self._tracer.step(
                state,
                AgentName.DISPROOF,
                title="Disproof agent disabled",
                status=TraceStatus.SKIPPED,
                output_summary="the leading explanation was not attacked; confidence is reported un-probed",
            )
            return run.state
        started = perf_counter()
        agent = self._disproof or DisproofAgent(execute_tool=run.call, settings=self._settings)
        queries = agent.queries_for(leader)
        items = await agent.probe(leader, run.state, run.ctx)
        state = _merge_probe_evidence(run.state, items)
        summary = agent.describe(leader, items, len(queries))
        probed = leader.model_copy(update={"disproof_searched": True, "verification_note": summary})
        state = state_ops.touch(
            state,
            hypotheses=[probed if h.hypothesis_id == leader.hypothesis_id else h for h in state.hypotheses],
        )
        state = state_ops.with_stage_latency(state, "disproof", _ms(started))
        state = await self._tracer.step(
            state,
            AgentName.DISPROOF,
            title=f"Probed {leader.hypothesis_id} for disproof",
            input_summary="; ".join(queries),
            output_summary=summary,
            evidence_ids=[item.evidence_id for item in items],
        )
        run.state = self._rescore(state, state.hypotheses)
        return run.state

    # -- contradictions ---------------------------------------------------
    async def contradictions(self, run: Run) -> InvestigationState:
        state = run.state
        if len(state.evidence.items) < 2:
            return state
        if run.contradictions_checked_at == len(state.evidence.items):
            run.state = await self._tracer.step(
                state,
                AgentName.CONTRADICTION,
                title="Conflict check already current",
                status=TraceStatus.SKIPPED,
                output_summary="no evidence has been added since the last contradiction check",
            )
            return run.state
        result = await run.call("detect_contradictions", {})
        state = observation.observe(run.state, [result])
        run.state = await self._tracer.step(
            state,
            AgentName.CONTRADICTION,
            title="Checked the evidence for conflicts",
            status=TraceStatus.OK if result.ok else TraceStatus.ERROR,
            output_summary=result.summary or result.error or "",
        )
        return run.state

    # -- verification -----------------------------------------------------
    async def verify(self, run: Run) -> InvestigationState:
        state = run.state
        leader = state.leading_hypothesis()
        claim = leader.description if leader else state.goal
        if not self._flags.get("verifier", True):
            run.state = await self._tracer.step(
                state,
                AgentName.VERIFIER,
                title="Verifier disabled",
                status=TraceStatus.SKIPPED,
                output_summary="the answer is reported without independent verification",
            )
            return run.state
        started = perf_counter()
        result = await run.call("verify_claim", {"claim": claim})
        state = observation.observe(run.state, [result])
        if state.verification is None:
            # The tool could not run (budget, flags); the deterministic checks still must.
            verification = await self._verifier.verify(
                claim, state.evidence, None, contradictions=state.contradictions, allow_llm=False
            )
            state = state_ops.touch(state, verification=verification)
        state = state_ops.with_stage_latency(state, "verify", _ms(started))
        checks = state.verification.checks if state.verification else {}
        run.state = await self._tracer.step(
            state,
            AgentName.VERIFIER,
            title="Verified the leading claim",
            input_summary=claim,
            output_summary=f"checks={checks}",
        )
        return run.state


def merge_hypotheses(existing: Sequence[Hypothesis], generated: Sequence[Hypothesis]) -> list[Hypothesis]:
    """Add newly generated explanations without duplicating the ones already held."""
    merged = list(existing)
    seen = {frozenset(content_tokens(h.description)) for h in merged}
    for hypothesis in generated:
        key = frozenset(content_tokens(hypothesis.description))
        if key in seen:
            continue
        seen.add(key)
        merged.append(hypothesis.model_copy(update={"hypothesis_id": f"H{len(merged) + 1}"}))
    return merged


def _merge_probe_evidence(
    state: InvestigationState, items: Sequence[EvidenceItem]
) -> InvestigationState:
    """Probe results update the stance of known evidence and admit the new."""
    known = {item.evidence_id for item in state.evidence.items}
    state = state_ops.with_updated_evidence(state, [i for i in items if i.evidence_id in known])
    state, _ = state_ops.with_evidence(state, [i for i in items if i.evidence_id not in known])
    return state


def _ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 3)
