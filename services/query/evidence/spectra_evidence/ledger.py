"""The evidence ledger: what was considered, what was used, what was rejected.

Ledgers are immutable value objects (``EvidenceLedger.with_items`` returns a new
one); this service owns the per-investigation index, persists items into the
evidence graph and answers the question the UI actually asks - *is this enough
evidence, and if not, which part is missing?*
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from spectra_config import Settings, get_settings
from spectra_config.logging import get_logger
from spectra_schemas import Claim, EvidenceItem, EvidenceLedger

from .graph import EvidenceGraph

log = get_logger(__name__)

# Sufficiency component weights.  Weight (relevance x reliability) leads because
# one authoritative, on-point record beats a pile of vague mentions; diversity is
# next because independent modalities are what makes a conclusion defensible.
SUFFICIENCY_WEIGHTS: Mapping[str, float] = {
    "weight": 0.35,
    "diversity": 0.25,
    "independence": 0.20,
    "count": 0.20,
}
# Saturation points: roughly three solid items (~0.7 weight each) is a complete
# case, from at least two independent sources.
TARGET_TOTAL_WEIGHT = 2.0
TARGET_EVIDENCE_COUNT = 3.0
TARGET_INDEPENDENT_SOURCES = 2.0
# Each item the disproof probe turned up against the claim removes real
# confidence, but counter-evidence must never zero a case out on its own.
CONTRADICTION_PENALTY_PER_ITEM = 0.15
MAX_CONTRADICTION_PENALTY = 0.45


class LedgerService:
    """Records evidence per investigation and scores its sufficiency."""

    def __init__(
        self,
        graph: EvidenceGraph | None = None,
        *,
        settings: Settings | None = None,
    ) -> None:
        self._graph = graph
        self._settings = settings or get_settings()
        self._ledgers: dict[str, EvidenceLedger] = {}
        self._items: dict[str, EvidenceItem] = {}

    # -- writes -----------------------------------------------------------
    async def record(self, investigation_id: str, items: Sequence[EvidenceItem]) -> EvidenceLedger:
        """Append items to an investigation's ledger and persist them."""
        current = self._ledgers.get(investigation_id, EvidenceLedger())
        updated = current.with_items(list(items))
        self._ledgers = {**self._ledgers, investigation_id: updated}
        self._items = {**self._items, **{item.evidence_id: item for item in items}}
        if self._graph is not None:
            for item in items:
                await self._graph.add_evidence(item, investigation_id=investigation_id)
        log.info(
            "ledger.recorded",
            investigation_id=investigation_id,
            added=len(items),
            total=len(updated.items),
        )
        return updated

    def reject(self, investigation_id: str, reason: str, count: int = 1) -> EvidenceLedger:
        """Record that candidates were considered and dropped, and why."""
        current = self._ledgers.get(investigation_id, EvidenceLedger())
        key = reason.strip() or "unspecified"
        reasons = {**current.rejection_reasons, key: current.rejection_reasons.get(key, 0) + count}
        updated = current.model_copy(
            update={
                "rejected_count": current.rejected_count + count,
                "considered_count": current.considered_count + count,
                "rejection_reasons": reasons,
            }
        )
        self._ledgers = {**self._ledgers, investigation_id: updated}
        return updated

    # -- queries ----------------------------------------------------------
    def get(self, evidence_id: str) -> EvidenceItem | None:
        return self._items.get(evidence_id)

    def for_investigation(self, investigation_id: str) -> EvidenceLedger:
        return self._ledgers.get(investigation_id, EvidenceLedger())

    def items_by_id(self, investigation_id: str) -> dict[str, EvidenceItem]:
        return {item.evidence_id: item for item in self.for_investigation(investigation_id).items}

    async def fetch(self, evidence_id: str) -> EvidenceItem | None:
        """``get`` with a graph fallback, so ids survive a process restart."""
        cached = self._items.get(evidence_id)
        if cached is not None or self._graph is None:
            return cached
        view = await self._graph.subgraph(evidence_id, depth=0)
        for node in view.nodes:
            if node.node_id != evidence_id:
                continue
            item = _item_from_payload(node.properties.get("payload"))
            if item is not None:
                self._items = {**self._items, evidence_id: item}
            return item
        return None

    def rejected_summary(self, investigation_id: str | None = None) -> dict[str, Any]:
        """Why candidate evidence did not make it into the answer."""
        ledgers = (
            [self.for_investigation(investigation_id)]
            if investigation_id
            else list(self._ledgers.values())
        )
        reasons: dict[str, int] = {}
        rejected = 0
        considered = 0
        for ledger in ledgers:
            rejected += ledger.rejected_count
            considered += ledger.considered_count
            for reason, count in ledger.rejection_reasons.items():
                reasons[reason] = reasons.get(reason, 0) + count
        return {
            "rejected_count": rejected,
            "considered_count": considered,
            "reasons": dict(sorted(reasons.items(), key=lambda pair: (-pair[1], pair[0]))),
        }

    # -- sufficiency ------------------------------------------------------
    def sufficiency(self, ledger: EvidenceLedger, claim: Claim) -> tuple[float, dict[str, Any]]:
        """Score how well this ledger supports one claim, and show the work."""
        supporting = _supporting_items(ledger, claim)
        sub_ledger = EvidenceLedger(items=supporting)
        total_weight = sum(item.weight for item in supporting)
        sources = {item.provenance.source_id for item in supporting}
        components = {
            "weight": min(total_weight / TARGET_TOTAL_WEIGHT, 1.0),
            "diversity": sub_ledger.diversity(),
            "independence": min(len(sources) / TARGET_INDEPENDENT_SOURCES, 1.0),
            "count": min(len(supporting) / TARGET_EVIDENCE_COUNT, 1.0),
        }
        contributions = {name: round(SUFFICIENCY_WEIGHTS[name] * value, 4) for name, value in components.items()}
        penalty = min(
            CONTRADICTION_PENALTY_PER_ITEM * len(claim.contradicting_evidence),
            MAX_CONTRADICTION_PENALTY,
        )
        score = round(max(0.0, min(1.0, sum(contributions.values()) - penalty)), 4)
        breakdown = {
            "score": score,
            "components": {name: round(value, 4) for name, value in components.items()},
            "weights": dict(SUFFICIENCY_WEIGHTS),
            "contributions": contributions,
            "contradiction_penalty": round(penalty, 4),
            "supporting_count": len(supporting),
            "independent_sources": len(sources),
            "total_weight": round(total_weight, 4),
            "threshold": self.threshold,
            "sufficient": score >= self.threshold,
        }
        log.debug("ledger.sufficiency", claim_id=claim.claim_id, score=score)
        return score, breakdown

    @property
    def threshold(self) -> float:
        return float(self._settings.sufficiency_threshold)

    def supports_abstention(self, score: float, threshold: float | None = None) -> bool:
        """True when the honest answer is 'insufficient evidence'."""
        return float(score) < (self.threshold if threshold is None else float(threshold))


def _supporting_items(ledger: EvidenceLedger, claim: Claim) -> list[EvidenceItem]:
    """Items linked to this claim, by either side of the link."""
    named = set(claim.supporting_evidence)
    return [
        item
        for item in ledger.items
        if item.evidence_id in named or claim.claim_id in item.claim_ids
    ]


def _item_from_payload(payload: Any) -> EvidenceItem | None:
    if not payload:
        return None
    try:
        data = json.loads(payload) if isinstance(payload, str) else payload
        return EvidenceItem.model_validate(data)
    except (ValueError, TypeError) as exc:
        log.warning("ledger.payload_unreadable", error=str(exc))
        return None


__all__ = [
    "CONTRADICTION_PENALTY_PER_ITEM",
    "MAX_CONTRADICTION_PENALTY",
    "SUFFICIENCY_WEIGHTS",
    "TARGET_EVIDENCE_COUNT",
    "TARGET_INDEPENDENT_SOURCES",
    "TARGET_TOTAL_WEIGHT",
    "LedgerService",
]
