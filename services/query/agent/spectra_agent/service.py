"""The investigation service: assembly, the plain search path, and cases.

Peer services are imported lazily inside the factory so this package imports
cleanly even while they are still landing, and any that cannot be constructed
simply leave their capability unavailable - reported, never faked.
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Callable, Sequence
from typing import Any

from spectra_config import Settings, get_settings
from spectra_config.logging import get_logger
from spectra_schemas import (
    ConfidenceLabel,
    InvestigationAnswer,
    InvestigationCase,
    InvestigationState,
    InvestigationStatus,
    PermissionContext,
    SearchMode,
    SearchRequest,
    SearchResponse,
)
from spectra_schemas import (
    case_id as new_case_id,
)

from .autopsy import AutopsyBuilder
from .context import AgentServices
from .explain import ExplanationBuilder
from .orchestrator import SpectraBrain
from .persistence import InMemoryStateStore, StateStore, store_for
from .streaming import TraceBroker
from .synthesis import ANSWER_EVIDENCE_LIMIT

log = get_logger(__name__)

# module path -> factory names to try, in order of preference
PEER_SERVICES: dict[str, tuple[str, tuple[str, ...]]] = {
    "search": ("spectra_search.service", ("get_search_service", "build_search_service", "SearchService")),
    "entities": (
        "spectra_entity_resolution.service",
        ("get_entity_resolution_service", "build_entity_resolution_service", "EntityResolutionService"),
    ),
    "evidence": ("spectra_evidence.service", ("get_evidence_service", "build_evidence_service", "EvidenceService")),
    "sources": ("spectra_connectors.service", ("get_source_service", "build_source_service", "SourceService")),
}


class InvestigationService:
    """Front door for the API layer."""

    def __init__(
        self,
        brain: SpectraBrain,
        store: StateStore | None = None,
        *,
        settings: Settings | None = None,
        services: AgentServices | None = None,
        broker: TraceBroker | None = None,
    ) -> None:
        self._brain = brain
        self._store = store or InMemoryStateStore()
        self._settings = settings or get_settings()
        self._services = services or AgentServices()
        self._broker = broker
        self._explainer = ExplanationBuilder()
        self._autopsy = AutopsyBuilder()

    # -- investigations ---------------------------------------------------
    async def investigate(
        self,
        question: str,
        *,
        mode: SearchMode = SearchMode.DEEP,
        ctx: PermissionContext | None = None,
        uploaded_asset_ids: Sequence[str] | None = None,
        investigation_id: str | None = None,
        case_id: str | None = None,
    ) -> InvestigationState:
        state = await self._brain.investigate(
            question,
            mode=mode,
            ctx=ctx,
            uploaded_asset_ids=uploaded_asset_ids,
            investigation_id=investigation_id,
        )
        if case_id:
            state = state.model_copy(update={"case_id": case_id})
            await self._store.save(state)
            await self._attach_to_case(case_id, state)
        return state

    async def continue_investigation(
        self, investigation_id: str, followup: str, ctx: PermissionContext | None = None
    ) -> InvestigationState:
        return await self._brain.continue_investigation(investigation_id, followup, ctx)

    async def get_state(self, investigation_id: str) -> InvestigationState | None:
        return await self._store.load(investigation_id)

    async def list_investigations(self, limit: int = 50) -> list[InvestigationState]:
        return await self._store.list(limit)

    # -- plain search -----------------------------------------------------
    async def run_search(self, request: SearchRequest, ctx: PermissionContext | None = None) -> SearchResponse:
        """The non-agentic path: retrieval only, no claims, no synthesis."""
        search = self._services.search
        if search is None:
            return SearchResponse(
                query=request.query,
                mode=request.mode,
                degraded=True,
                degraded_reasons=["the search service is not available in this deployment"],
            )
        permissions = ctx or PermissionContext()
        if request.image_asset_id and hasattr(search, "search_by_image"):
            return await search.search_by_image(request.image_asset_id, permissions)
        return await search.search(request, permissions)

    # -- cases ------------------------------------------------------------
    async def create_case(self, title: str, question: str, *, case_id: str | None = None) -> InvestigationCase:
        case = InvestigationCase(case_id=case_id or new_case_id(), title=title, question=question)
        await self._store.save_case(case)
        return case

    async def get_case(self, case_id: str) -> InvestigationCase | None:
        return await self._store.load_case(case_id)

    async def list_cases(self, limit: int = 50) -> list[InvestigationCase]:
        return await self._store.list_cases(limit)

    async def reopen_case(self, case_id: str) -> InvestigationCase:
        case = await self._require_case(case_id)
        reopened = case.model_copy(update={"status": InvestigationStatus.RUNNING})
        await self._store.save_case(reopened)
        return reopened

    async def continue_case(
        self, case_id: str, followup: str, ctx: PermissionContext | None = None
    ) -> InvestigationState:
        case = await self._require_case(case_id)
        if not case.investigation_ids:
            return await self.investigate(followup, ctx=ctx, case_id=case_id)
        state = await self._brain.continue_investigation(case.investigation_ids[-1], followup, ctx)
        await self._attach_to_case(case_id, state)
        return state

    async def export_case(self, case_id: str) -> dict[str, Any]:
        case = await self._require_case(case_id)
        investigations = [await self._store.load(i) for i in case.investigation_ids]
        return {
            "case": case.model_dump(mode="json"),
            "investigations": [
                self.to_answer(state).model_dump(mode="json") for state in investigations if state
            ],
        }

    async def _require_case(self, case_id: str) -> InvestigationCase:
        case = await self._store.load_case(case_id)
        if case is None:
            raise ValueError(f"case '{case_id}' was not found")
        return case

    async def _attach_to_case(self, case_id: str, state: InvestigationState) -> None:
        case = await self._store.load_case(case_id)
        if case is None:
            return
        ids = list(case.investigation_ids)
        if state.investigation_id not in ids:
            ids.append(state.investigation_id)
        entity_ids = list(dict.fromkeys([*case.entity_ids, *state.entities]))
        await self._store.save_case(
            case.model_copy(
                update={
                    "investigation_ids": ids,
                    "entity_ids": entity_ids,
                    "status": state.status,
                    "evidence_count": len(state.evidence.items),
                    "contradiction_count": len(state.contradictions),
                    "claim_count": len(state.claims),
                    "confidence": state.confidence,
                    "updated_at": state.updated_at,
                }
            )
        )

    # -- response contract ------------------------------------------------
    def to_answer(self, state: InvestigationState) -> InvestigationAnswer:
        """The structured contract the application reads - never free text."""
        cited = sorted(state.evidence.items, key=lambda i: i.weight, reverse=True)[:ANSWER_EVIDENCE_LIMIT]
        evidence = [
            {
                "label": f"E{index + 1}",
                "evidence_id": item.evidence_id,
                "summary": item.summary,
                "excerpt": item.excerpt,
                "modality": item.modality.value,
                "stance": item.stance.value,
                "citation": item.citation(),
                "weight": item.weight,
                # docs/api.md specifies these, and the console renders the
                # reliability reason on hover - omitting them made every item
                # look unscored.
                "kind": item.kind.value,
                "relevance": item.relevance,
                "reliability": item.reliability,
                "reliability_reason": item.reliability_reason,
                "entities": list(item.entities),
                "occurred_at": item.occurred_at.isoformat() if item.occurred_at else None,
                "retrieved_by": item.retrieved_by,
                "provenance": item.provenance.model_dump(mode="json"),
            }
            for index, item in enumerate(cited)
        ]
        return InvestigationAnswer(
            investigation_id=state.investigation_id,
            answer=state.answer,
            confidence=state.confidence,
            confidence_label=ConfidenceLabel.from_score(state.confidence),
            status=state.answer_status,
            entities=[{"entity_id": entity} for entity in state.entities],
            evidence=evidence,
            contradictions=list(state.contradictions),
            timeline=list(state.timeline),
            claims=list(state.claims),
            application_links=list(state.application_links),
            explanation=self._explainer.build(state),
            autopsy=self._autopsy.build(state),
            metrics=state.metrics,
            degraded=state.degraded,
            degraded_reasons=list(state.degraded_reasons),
            followups=list(state.followups),
        )

    def subscribe(self, investigation_id: str) -> Any:
        """Async iterator of trace steps for the SSE endpoint."""
        if self._broker is None:
            raise RuntimeError("no TraceBroker was configured for this service")
        return self._broker.subscribe(investigation_id)


async def load_peer_services(settings: Settings | None = None) -> AgentServices:
    """Construct the peer services that are importable in this deployment."""
    resolved = settings or get_settings()
    built: dict[str, Any] = {}
    for attribute, (module_path, factories) in PEER_SERVICES.items():
        built[attribute] = await _instantiate(module_path, factories, resolved)
    storage = await _storage(resolved)
    gateway = await _gateway(resolved)
    return AgentServices(
        search=built["search"],
        entities=built["entities"],
        evidence=built["evidence"],
        sources=built["sources"],
        storage=storage,
        gateway=gateway,
    )


async def build_investigation_service(
    settings: Settings | None = None,
    *,
    services: AgentServices | None = None,
    broker: TraceBroker | None = None,
    flags_provider: Callable[[], dict[str, bool]] | None = None,
) -> InvestigationService:
    """Assemble the Brain with every injected dependency it can reach.

    ``flags_provider`` lets the caller supply agent flags that change at
    runtime (the Agent Control Center); without it the Brain falls back to the
    configured settings.
    """
    resolved = settings or get_settings()
    resolved_services = services or await load_peer_services(resolved)
    resolved_broker = broker or TraceBroker()
    store = store_for(resolved_services.storage)
    brain = SpectraBrain(
        flags_provider=flags_provider,
        services=resolved_services,
        settings=resolved,
        broker=resolved_broker,
        save_state=store.save,
        load_state=store.load,
    )
    return InvestigationService(
        brain, store, settings=resolved, services=resolved_services, broker=resolved_broker
    )


async def _instantiate(module_path: str, factories: Sequence[str], settings: Settings) -> Any:
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        log.info("agent.peer_unavailable", module=module_path, reason=str(exc))
        return None
    for name in factories:
        factory = getattr(module, name, None)
        if factory is None:
            continue
        try:
            return await _maybe_await(_invoke(factory, settings))
        except Exception as exc:
            log.warning("agent.peer_construction_failed", module=module_path, factory=name, error=str(exc))
    log.info("agent.peer_no_factory", module=module_path)
    return None


def _invoke(factory: Any, settings: Settings) -> Any:
    try:
        parameters = inspect.signature(factory).parameters
    except (TypeError, ValueError):  # pragma: no cover - builtins
        return factory()
    if "settings" in parameters:
        return factory(settings=settings)
    positional = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    required = [
        p for p in parameters.values() if p.default is inspect.Parameter.empty and p.kind in positional
    ]
    if required:
        return factory(settings)
    return factory()


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _storage(settings: Settings) -> Any:
    try:
        from spectra_storage.facade import get_storage
    except ImportError:  # pragma: no cover - storage always ships with the platform
        return None
    try:
        return await get_storage(settings)
    except Exception as exc:
        log.warning("agent.storage_unavailable", error=str(exc))
        return None


async def _gateway(settings: Settings) -> Any:
    try:
        from spectra_ai_core.gateway import get_gateway
    except ImportError:
        return None
    try:
        return await get_gateway(settings)
    except Exception as exc:
        log.warning("agent.gateway_unavailable", error=str(exc))
        return None
