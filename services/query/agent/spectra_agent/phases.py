"""The reasoning phases: state the claims, attack them, reconcile, verify.

These are separated from the retrieval loop because they answer a different
question.  Retrieval asks "what else is there?"; these ask "does what we have
actually support the conclusion?" - including the disproof phase, whose whole
purpose is to try to knock the leading claim down.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from time import perf_counter

from spectra_config import Settings
from spectra_config.logging import get_logger
from spectra_schemas import (
    AgentName,
    Claim,
    EvidenceItem,
    InvestigationState,
    TraceStatus,
    claim_id,
)

from . import observation, state_ops
from .agents.claim import ClaimBuilder
from .agents.disproof import DisproofAgent
from .agents.verifier import Verifier
from .lexicons import content_tokens
from .run_context import Run
from .tracing import Tracer

log = get_logger(__name__)


class ReasoningPhases:
    """Claim building and scoring, disproof, contradiction sweep and verification."""

    def __init__(
        self,
        *,
        settings: Settings,
        flags: Mapping[str, bool],
        claims: ClaimBuilder,
        verifier: Verifier,
        tracer: Tracer,
        disproof: DisproofAgent | None = None,
    ) -> None:
        self._settings = settings
        self._flags = dict(flags)
        self._claims = claims
        self._verifier = verifier
        self._tracer = tracer
        self._disproof = disproof

    # -- claims -----------------------------------------------------------
    async def build_claims(
        self, state: InvestigationState, *, allow_llm: bool = True
    ) -> InvestigationState:
        """Build (when needed), link and score the claims the evidence supports."""
        if not self._flags.get("claim", True):
            return await self._tracer.step(
                state,
                AgentName.CLAIM,
                title="Claim builder disabled",
                status=TraceStatus.SKIPPED,
                output_summary="no claims were stated; evidence is reported as retrieved",
            )
        started = perf_counter()
        claims = list(state.claims)
        if not claims or self._claims.should_build_more(state):
            built = await self._claims.build(state, state.evidence.items, allow_llm=allow_llm)
            claims = merge_claims(state, claims, built)
        claims = self._claims.attach(claims, state.evidence.items)
        state = self._rescore(state, claims)
        state = state_ops.with_stage_latency(state, "claims", _ms(started))
        return await self._tracer.step(
            state,
            AgentName.CLAIM,
            title=f"Stated {len(state.claims)} claim(s) from the evidence",
            output_summary=_leader_summary(state),
        )

    def _rescore(self, state: InvestigationState, claims: Sequence[Claim]) -> InvestigationState:
        """Re-score every claim on its own evidence - no share is taken from any other."""
        scored = [self._claims.score(claim, state.evidence) for claim in claims]
        return state_ops.touch(state, claims=self._claims.rank(scored))

    # -- disproof ---------------------------------------------------------
    async def disproof(self, run: Run) -> InvestigationState:
        """Attack the leading claim; 'nothing found' is a recorded result."""
        state = run.state
        leader = state.leading_claim()
        if leader is None:
            return state
        if not self._flags.get("disproof", True):
            run.state = await self._tracer.step(
                state,
                AgentName.DISPROOF,
                title="Disproof agent disabled",
                status=TraceStatus.SKIPPED,
                output_summary="the leading claim was not attacked; confidence is reported un-probed",
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
            claims=[probed if c.claim_id == leader.claim_id else c for c in state.claims],
        )
        state = state_ops.with_stage_latency(state, "disproof", _ms(started))
        state = await self._tracer.step(
            state,
            AgentName.DISPROOF,
            title=f"Probed {leader.claim_id} for disproof",
            input_summary="; ".join(queries),
            output_summary=summary,
            evidence_ids=[item.evidence_id for item in items],
        )
        run.state = self._rescore(state, state.claims)
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
        leader = state.leading_claim()
        statement = leader.text if leader else state.goal
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
        result = await run.call("verify_claim", {"claim": statement})
        state = observation.observe(run.state, [result])
        if state.verification is None:
            # The tool could not run (budget, flags); the deterministic checks still must.
            verification = await self._verifier.verify(
                statement, state.evidence, None, contradictions=state.contradictions, allow_llm=False
            )
            state = state_ops.touch(state, verification=verification)
        state = _record_verification(state, leader)
        state = state_ops.with_stage_latency(state, "verify", _ms(started))
        checks = state.verification.checks if state.verification else {}
        run.state = await self._tracer.step(
            state,
            AgentName.VERIFIER,
            title="Verified the leading claim",
            input_summary=statement,
            output_summary=f"checks={checks}",
        )
        return run.state


def merge_claims(
    state: InvestigationState, existing: Sequence[Claim], built: Sequence[Claim]
) -> list[Claim]:
    """Add newly stated claims without duplicating the ones already held."""
    merged = list(existing)
    seen = {frozenset(content_tokens(claim.text)) for claim in merged}
    for claim in built:
        key = frozenset(content_tokens(claim.text))
        if key in seen:
            continue
        seen.add(key)
        merged.append(
            claim.model_copy(update={"claim_id": claim_id(state.investigation_id, len(merged))})
        )
    return merged


def _record_verification(state: InvestigationState, leader: Claim | None) -> InvestigationState:
    """Mark the leading claim with the verdict the Verifier reached."""
    verification = state.verification
    if leader is None or verification is None:
        return state
    verified = leader.model_copy(
        update={
            "verified": verification.supported,
            "verification_note": "; ".join(
                part for part in (leader.verification_note, verification.note) if part
            ),
        }
    )
    return state_ops.touch(
        state, claims=[verified if c.claim_id == leader.claim_id else c for c in state.claims]
    )


def _leader_summary(state: InvestigationState) -> str:
    leader = state.leading_claim()
    if leader is None:
        return "no claim could be stated from the retrieved evidence"
    return f"leading: {leader.claim_id} {leader.text} ({leader.status.value}, {leader.confidence:.2f})"


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
