"""``EvidenceService`` - the single object the agent layer talks to.

It composes the reliability scorer, evidence builder, evidence graph, timeline
builder, contradiction radar, application resolver and ledger so an agent never
has to wire six collaborators together (or forget one).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from spectra_config import Settings, get_settings
from spectra_config.logging import get_logger
from spectra_schemas import (
    ApplicationLink,
    CanonicalEntity,
    Claim,
    Contradiction,
    EvidenceItem,
    EvidenceLedger,
    EvidenceStance,
    GraphView,
    SearchHit,
    SourceDescriptor,
    TimelineEvent,
)
from spectra_storage.facade import get_storage

from .application_resolver import ApplicationResolver, VerifyCallable
from .builder import EvidenceBuilder
from .contradiction import ContradictionRadar
from .graph import EvidenceGraph
from .ledger import LedgerService
from .reliability import ReliabilityScorer
from .timeline import DEFAULT_WINDOW, TimelineBuilder

log = get_logger(__name__)


class EvidenceService:
    """Facade over the whole evidence layer."""

    def __init__(
        self,
        *,
        graph: EvidenceGraph,
        scorer: ReliabilityScorer | None = None,
        builder: EvidenceBuilder | None = None,
        timeline: TimelineBuilder | None = None,
        radar: ContradictionRadar | None = None,
        resolver: ApplicationResolver | None = None,
        ledger: LedgerService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.scorer = scorer or ReliabilityScorer()
        self.builder = builder or EvidenceBuilder(self.scorer)
        self.graph = graph
        self.timeline = timeline or TimelineBuilder()
        self.radar = radar or ContradictionRadar(scorer=self.scorer)
        self.resolver = resolver or ApplicationResolver(settings=self.settings)
        self.ledger = ledger or LedgerService(graph, settings=self.settings)

    # -- evidence ---------------------------------------------------------
    def evidence_from_hits(
        self,
        hits: Sequence[SearchHit],
        *,
        claim_scope: str = "",
        entity_ids: Sequence[str] = (),
        entity_terms: Sequence[str] = (),
        retrieved_by: str = "",
        stance: EvidenceStance = EvidenceStance.NEUTRAL,
        sources: Mapping[str, SourceDescriptor] | None = None,
    ) -> list[EvidenceItem]:
        items = self.builder.from_search_hits(
            hits,
            claim_scope=claim_scope,
            entity_ids=entity_ids,
            entity_terms=entity_terms,
            retrieved_by=retrieved_by,
            stance=stance,
            sources=sources,
        )
        return self.builder.deduplicate(items)

    def evidence_from_rows(
        self, rows: Sequence[Mapping[str, Any]], **kwargs: Any
    ) -> list[EvidenceItem]:
        return self.builder.deduplicate(self.builder.from_database_rows(rows, **kwargs))

    async def record(self, investigation_id: str, items: Sequence[EvidenceItem]) -> EvidenceLedger:
        return await self.ledger.record(investigation_id, items)

    async def ingest_hits(
        self, investigation_id: str, hits: Sequence[SearchHit], **kwargs: Any
    ) -> tuple[list[EvidenceItem], EvidenceLedger]:
        """Build, deduplicate, persist - the common retrieval -> ledger path."""
        items = self.evidence_from_hits(hits, **kwargs)
        ledger = await self.record(investigation_id, items)
        return items, ledger

    # -- contradictions ---------------------------------------------------
    def contradictions(
        self, evidence: Sequence[EvidenceItem], entity_ids: Sequence[str] = ()
    ) -> list[Contradiction]:
        return self.radar.detect(evidence, entity_ids)

    def resolve_contradictions(
        self, contradictions: Sequence[Contradiction], evidence: Sequence[EvidenceItem]
    ) -> list[Contradiction]:
        by_id = {item.evidence_id: item for item in evidence}
        return [self.radar.resolve(contradiction, by_id) for contradiction in contradictions]

    async def explain_contradiction(
        self,
        contradiction: Contradiction,
        evidence: Sequence[EvidenceItem],
        *,
        use_llm: bool = False,
    ) -> str:
        """Explain a contradiction; a model may only rephrase the verdict."""
        by_id = {item.evidence_id: item for item in evidence}
        if not use_llm:
            return self.radar.explain(contradiction, by_id)
        gateway = await _optional_gateway()
        return await self.radar.phrase(contradiction, by_id, gateway=gateway)

    # -- timeline ---------------------------------------------------------
    def build_timeline(
        self,
        evidence: Sequence[EvidenceItem],
        entities: Sequence[CanonicalEntity] = (),
        extra_events: Sequence[TimelineEvent] = (),
        *,
        asset_starts: Mapping[str, datetime] | None = None,
    ) -> list[TimelineEvent]:
        return self.timeline.build(evidence, entities, extra_events, asset_starts=asset_starts)

    def describe_timeline(self, events: Sequence[TimelineEvent]) -> list[str]:
        return self.timeline.describe(events)

    def timeline_window(
        self,
        events: Sequence[TimelineEvent],
        around: datetime,
        before: timedelta = DEFAULT_WINDOW,
        after: timedelta = DEFAULT_WINDOW,
    ) -> list[TimelineEvent]:
        return self.timeline.window(events, around, before, after)

    def latest_version_of(self, items: Sequence[EvidenceItem]) -> EvidenceItem | None:
        return self.timeline.latest_version_of(items)

    async def persist_timeline(
        self, investigation_id: str, events: Sequence[TimelineEvent]
    ) -> list[str]:
        return await self.graph.add_timeline_order(events, investigation_id=investigation_id)

    # -- applications -----------------------------------------------------
    def application_links(self, entities: Sequence[CanonicalEntity]) -> list[ApplicationLink]:
        return self.resolver.resolve_many(entities)

    async def persist_application_links(self, links: Sequence[ApplicationLink]) -> list[str]:
        return [await self.graph.link_application_record(link) for link in links]

    def with_verifier(self, verify: VerifyCallable | None) -> EvidenceService:
        """Return a NEW service whose application links are database-verified."""
        return EvidenceService(
            graph=self.graph,
            scorer=self.scorer,
            builder=self.builder,
            timeline=self.timeline,
            radar=self.radar,
            resolver=self.resolver.with_verifier(verify),
            ledger=self.ledger,
            settings=self.settings,
        )

    # -- sufficiency / graph ---------------------------------------------
    def sufficiency(
        self, ledger: EvidenceLedger, claim: Claim
    ) -> tuple[float, dict[str, Any]]:
        return self.ledger.sufficiency(ledger, claim)

    def supports_abstention(self, score: float, threshold: float | None = None) -> bool:
        return self.ledger.supports_abstention(score, threshold)

    async def investigation_graph(self, investigation_id: str, *, depth: int = 1) -> GraphView:
        return await self.graph.investigation_view(investigation_id, depth=depth)

    async def entity_graph(self, entity_id: str, *, depth: int = 2) -> GraphView:
        return await self.graph.neighbours_of_entity(entity_id, depth=depth)


async def build_evidence_service(
    *,
    settings: Settings | None = None,
    verify: VerifyCallable | None = None,
    sources: Mapping[str, SourceDescriptor] | None = None,
) -> EvidenceService:
    """Construct the service against the configured storage backends."""
    resolved = settings or get_settings()
    storage = await get_storage(resolved)
    scorer = ReliabilityScorer(sources=sources)
    graph = EvidenceGraph(storage.graph)
    service = EvidenceService(
        graph=graph,
        scorer=scorer,
        builder=EvidenceBuilder(scorer),
        radar=ContradictionRadar(scorer=scorer),
        resolver=ApplicationResolver(settings=resolved, verify=verify),
        ledger=LedgerService(graph, settings=resolved),
        settings=resolved,
    )
    log.info("evidence.service_ready", graph_backend=getattr(storage.graph, "backend_name", "unknown"))
    return service


async def _optional_gateway() -> object | None:
    """The model gateway if it is available - explanation works without it."""
    try:
        from spectra_ai_core.gateway import get_gateway

        return await get_gateway()
    except Exception as exc:
        log.warning("evidence.gateway_unavailable", error=str(exc))
        return None


__all__ = ["EvidenceService", "build_evidence_service"]
