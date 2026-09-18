"""SPECTRA Brain - the dynamic investigation loop.

    understand -> plan -> select tools -> execute (parallel where independent)
      -> observe -> update evidence / entities / graph
      -> sufficient? --no--> replan (new tools OR new hypotheses) --loop
                     --yes-> disproof -> contradictions -> verify -> synthesise

The loop is driven by the evidence gap, not by a script: what gets called next
is decided from what the last round actually returned.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from time import perf_counter
from typing import Any

from spectra_config import Settings, get_settings
from spectra_config.budgets import budget_for
from spectra_config.logging import get_logger, investigation_id_var
from spectra_schemas import (
    AgentName,
    AnswerStatus,
    HypothesisStatus,
    InvestigationState,
    InvestigationStatus,
    PermissionContext,
    SearchMode,
    TraceStatus,
)
from spectra_schemas import (
    investigation_id as new_investigation_id,
)

from . import availability, conclusion, observation, state_ops, sufficiency
from .agents.disproof import DisproofAgent
from .agents.hypothesis import HypothesisEngine
from .agents.verifier import Verifier
from .autopsy import AutopsyBuilder
from .context import AgentServices, ToolContext
from .execution import ExecutionEngine
from .explain import ExplanationBuilder
from .model_usage import wrap
from .phases import ReasoningPhases
from .planner import PlannedCall, initial_plan, replan
from .run_context import Run
from .streaming import TraceBroker
from .synthesis import AnswerSynthesiser
from .thresholds import MIN_DEEP_ITERATIONS
from .tools import ToolRegistry, build_registry
from .tracing import OnTrace, Tracer
from .understanding import QueryUnderstandingService

log = get_logger(__name__)

SaveState = Callable[[InvestigationState], Awaitable[None]]
LoadState = Callable[[str], Awaitable[InvestigationState | None]]


class SpectraBrain:
    """The agent controller."""

    def __init__(
        self,
        *,
        services: AgentServices,
        settings: Settings | None = None,
        registry: ToolRegistry | None = None,
        understanding: QueryUnderstandingService | None = None,
        hypotheses: HypothesisEngine | None = None,
        disproof: DisproofAgent | None = None,
        verifier: Verifier | None = None,
        synthesiser: AnswerSynthesiser | None = None,
        explainer: ExplanationBuilder | None = None,
        autopsy: AutopsyBuilder | None = None,
        broker: TraceBroker | None = None,
        on_trace: OnTrace | None = None,
        save_state: SaveState | None = None,
        load_state: LoadState | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._recorder = wrap(services.gateway)
        self._services = replace(services, gateway=self._recorder) if self._recorder else services
        self._flags = self._settings.agent_flags()
        self._registry = registry or build_registry(self._flags)
        self._understanding = understanding or QueryUnderstandingService(self._settings, self._recorder)
        self._hypotheses = hypotheses or HypothesisEngine(self._settings, self._recorder)
        self._disproof = disproof
        self._verifier = verifier or Verifier(self._settings, self._recorder)
        self._synthesiser = synthesiser or AnswerSynthesiser(self._settings, self._recorder)
        self._explainer = explainer or ExplanationBuilder()
        self._autopsy = autopsy or AutopsyBuilder()
        self._broker = broker
        self._save_state = save_state
        self._load_state = load_state
        self._tracer = Tracer(broker, on_trace)
        self._engine = ExecutionEngine(self._registry, self._tracer.emit)
        self._phases = ReasoningPhases(
            settings=self._settings,
            flags=self._flags,
            hypotheses=self._hypotheses,
            verifier=self._verifier,
            tracer=self._tracer,
            disproof=disproof,
        )

    # -- public API -------------------------------------------------------
    async def investigate(
        self,
        question: str,
        *,
        mode: SearchMode = SearchMode.DEEP,
        ctx: PermissionContext | None = None,
        uploaded_asset_ids: Sequence[str] | None = None,
        investigation_id: str | None = None,
    ) -> InvestigationState:
        permissions = ctx or PermissionContext()
        state = self._new_state(question, mode, permissions, uploaded_asset_ids, investigation_id)
        return await self._run(state, permissions)

    async def continue_investigation(
        self, investigation_id: str, followup: str, ctx: PermissionContext | None = None
    ) -> InvestigationState:
        """Resume a persisted investigation with a follow-up question."""
        if self._load_state is None:
            raise RuntimeError("no load_state callable was injected; cannot resume an investigation")
        previous = await self._load_state(investigation_id)
        if previous is None:
            raise ValueError(f"investigation '{investigation_id}' was not found")
        permissions = ctx or PermissionContext(user_id=previous.user_id or "local-user")
        budget = state_ops.budget_from(previous.mode, budget_for(previous.mode.value, self._settings))
        state = state_ops.touch(
            previous,
            goal=followup,
            status=InvestigationStatus.RUNNING,
            budget=budget,
            followups=[*previous.followups, followup],
            understanding=None,
            answer="",
            claims=[],
            verification=None,
        )
        return await self._run(state, permissions)

    def explain(self, state: InvestigationState) -> Any:
        return self._explainer.build(state)

    def autopsy(self, state: InvestigationState) -> Any:
        return self._autopsy.build(state)

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    # -- run --------------------------------------------------------------
    async def _run(self, state: InvestigationState, permissions: PermissionContext) -> InvestigationState:
        token = investigation_id_var.set(state.investigation_id)
        started = perf_counter()
        try:
            state = self._apply_availability(state)
            ctx = self._tool_context(state, permissions)
            state = await self._understand(state, ctx)
            if state.mode is SearchMode.FAST:
                state = await self._fast(state, ctx, started)
            else:
                state = await self._deep(state, ctx, started)
        except Exception as exc:  # a failed investigation must still return state
            log.exception("brain.failed", error=str(exc), investigation_id=state.investigation_id)
            state = state_ops.touch(
                state,
                status=InvestigationStatus.FAILED,
                answer_status=AnswerStatus.FAILED,
                answer=f"The investigation could not be completed: {type(exc).__name__}: {exc}",
            )
            state = state_ops.degraded(state, f"investigation failed: {type(exc).__name__}")
        finally:
            investigation_id_var.reset(token)
        state = self._finalise(state, started)
        await self._persist(state)
        await self._tracer.close(state.investigation_id)
        return state

    def _new_state(
        self,
        question: str,
        mode: SearchMode,
        permissions: PermissionContext,
        uploaded_asset_ids: Sequence[str] | None,
        investigation_id: str | None,
    ) -> InvestigationState:
        budget = state_ops.budget_from(mode, budget_for(mode.value, self._settings))
        return InvestigationState(
            investigation_id=investigation_id or new_investigation_id(),
            goal=question,
            mode=mode,
            status=InvestigationStatus.RUNNING,
            budget=budget,
            uploaded_asset_ids=list(uploaded_asset_ids or []),
            user_id=permissions.user_id,
            role=permissions.role.value,
        )

    def _tool_context(self, state: InvestigationState, permissions: PermissionContext) -> ToolContext:
        return ToolContext(
            investigation_id=state.investigation_id,
            permissions=permissions,
            services=self._services,
            budget=state.budget,
            settings=self._settings,
            mode=state.mode,
            goal=state.goal,
            uploaded_asset_ids=tuple(state.uploaded_asset_ids),
            agent_flags=dict(self._flags),
        )

    def _apply_availability(self, state: InvestigationState) -> InvestigationState:
        report = availability.build(self._flags, self._registry, self._services)
        state = state_ops.touch(state, agent_availability=report)
        for reason in availability.degraded_reasons(report):
            state = state_ops.degraded(state, reason)
        return state

    # -- stages -----------------------------------------------------------
    async def _understand(self, state: InvestigationState, ctx: ToolContext) -> InvestigationState:
        started = perf_counter()
        allow_llm = state.mode is not SearchMode.FAST
        understanding = await self._understanding.analyse(state.goal, ctx, allow_llm=allow_llm)
        state = state_ops.touch(state, understanding=understanding)
        state = state_ops.with_stage_latency(state, "understand", _ms(started))
        return await self._tracer.step(
            state,
            AgentName.BRAIN,
            title="Understood the question",
            output_summary=(
                f"intent={understanding.intent.value}, complexity={understanding.complexity}, "
                f"ids={understanding.detected_ids or 'none'} ({understanding.produced_by})"
            ),
            input_summary=understanding.explanation,
        )

    async def _fast(self, state: InvestigationState, ctx: ToolContext, started: float) -> InvestigationState:
        run = Run(state, ctx, self._engine)
        plan = initial_plan(state.understanding, self._available(), SearchMode.FAST)  # type: ignore[arg-type]
        results = await run.batch(plan)
        state = observation.observe(run.state, results)
        run.state = state
        if not state.evidence.items and "search_documents" in self._available():
            results = await run.batch(
                [
                    PlannedCall(
                        "search_documents",
                        {"query": state.understanding.rewritten if state.understanding else state.goal},
                        "the exact lookup returned nothing, so documents are searched before answering",
                    )
                ]
            )
            state = observation.observe(run.state, results)
            run.state = state
        state = await self._link_application(run, state)
        state = await self._tracer.step(
            state,
            AgentName.HYPOTHESIS,
            title="Hypothesis engine skipped",
            status=TraceStatus.SKIPPED,
            output_summary="fast mode answers from exact retrieval only; run deep mode for competing explanations",
        )
        state = state_ops.with_iteration(state, perf_counter() - started)
        return await self._conclude(state, allow_llm=False)

    async def _deep(self, state: InvestigationState, ctx: ToolContext, started: float) -> InvestigationState:
        run = Run(state, ctx, self._engine)
        plan = initial_plan(state.understanding, self._available(), SearchMode.DEEP)  # type: ignore[arg-type]
        while plan:
            results = await run.batch(plan)
            run.state = observation.observe(run.state, results)
            run.state = await self._phases.reason(run.state)
            run.state = state_ops.with_iteration(run.state, perf_counter() - started)
            await self._persist(run.state)
            exhaustion = self._budget_stop(run.state, perf_counter() - started)
            if exhaustion is not None:
                run.state = state_ops.exhausted(run.state, exhaustion)
            stop = exhaustion or self._sufficiency_stop(run.state)
            if stop is not None:
                run.state = await self._tracer.step(
                    run.state, AgentName.BRAIN, title="Stopping the loop", output_summary=stop
                )
                break
            plan = replan(run.state, self._available())
            if plan:
                run.state = await self._tracer.step(
                    run.state,
                    AgentName.BRAIN,
                    title=f"Replanning iteration {run.state.budget.iterations_used + 1}",
                    output_summary="; ".join(call.describe() for call in plan),
                )
        await self._phases.disproof(run)
        await self._phases.contradictions(run)
        state = await self._phases.verify(run)
        return await self._conclude(state, allow_llm=True)

    async def _link_application(self, run: Run, state: InvestigationState) -> InvestigationState:
        if not state.entities or state.budget.tool_calls_remaining <= 0:
            return state
        run.state = state
        result = await run.call("open_application_record", {"entity_id": state.entities[0]})
        return observation.observe(run.state, [result])

    # -- conclusion -------------------------------------------------------
    async def _conclude(self, state: InvestigationState, *, allow_llm: bool) -> InvestigationState:
        started = perf_counter()
        answer, claims = await self._synthesiser.compose(state, allow_llm=allow_llm)
        score = sufficiency.compute(state.evidence)
        status = conclusion.answer_status(state, score, self._settings.sufficiency_threshold)
        confidence = conclusion.confidence_for(state, claims, score, status)
        state = state_ops.touch(
            state,
            answer=answer,
            claims=claims,
            answer_status=status,
            confidence=confidence,
            followups=conclusion.followups(state),
        )
        state = state_ops.with_stage_latency(state, "synthesis", _ms(started))
        return await self._tracer.step(
            state,
            AgentName.BRAIN,
            title="Composed the answer",
            output_summary=f"status={status.value}, confidence={confidence:.2f}, claims={len(claims)}",
            evidence_ids=[e for claim in claims for e in claim.evidence_ids],
        )

    def _finalise(self, state: InvestigationState, started: float) -> InvestigationState:
        models, latency = self._recorder.snapshot() if self._recorder else ([], {})
        metrics = state.metrics.model_copy(
            update={
                "total_latency_ms": round((perf_counter() - started) * 1000, 3),
                "models_used": models,
                "model_latency_ms": latency,
            }
        )
        status = state.status if state.status is InvestigationStatus.FAILED else InvestigationStatus.COMPLETED
        state = state_ops.with_elapsed(state, perf_counter() - started)
        return state_ops.touch(state, metrics=metrics, status=status)

    # -- plumbing ---------------------------------------------------------
    def _available(self) -> list[str]:
        return self._registry.available_names(self._flags)

    def _budget_stop(self, state: InvestigationState, elapsed: float) -> str | None:
        """The reason the budget forces a stop, if it does."""
        budget = state.budget
        if budget.tool_calls_remaining <= 0:
            return f"tool-call budget exhausted ({budget.tool_calls_used}/{budget.max_tool_calls} calls used)"
        if budget.iterations_used >= budget.max_iterations:
            return f"iteration budget exhausted ({budget.iterations_used}/{budget.max_iterations})"
        if elapsed >= budget.max_latency_seconds:
            return f"latency budget exhausted ({elapsed:.1f}s of {budget.max_latency_seconds:.1f}s)"
        return None

    def _sufficiency_stop(self, state: InvestigationState) -> str | None:
        """The reason the evidence allows a stop, if it does."""
        if state.budget.iterations_used < MIN_DEEP_ITERATIONS:
            return None
        if sufficiency.compute(state.evidence) < self._settings.sufficiency_threshold:
            return None
        leader = state.leading_hypothesis()
        # Confidence is a share across competing explanations, so the stop test
        # reads the leader's *status* - its own balance of evidence.
        if leader is None or leader.status is HypothesisStatus.SUPPORTED:
            return "sufficient evidence gathered, with a supported leading explanation"
        return None

    async def _persist(self, state: InvestigationState) -> None:
        if self._save_state is None:
            return
        try:
            await self._save_state(state)
        except Exception as exc:  # persistence is best-effort, never fatal
            log.warning("state.save_failed", error=str(exc), investigation_id=state.investigation_id)


# -- module helpers -------------------------------------------------------
def _ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 3)
