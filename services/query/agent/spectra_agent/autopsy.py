"""Search autopsy - the forensic record of one investigation.

Everything here is read off the investigation state; the autopsy adds no new
computation beyond counting, so what it shows is exactly what happened.
"""

from __future__ import annotations

from spectra_schemas import ClaimStatus, InvestigationState, SearchAutopsy


class AutopsyBuilder:
    """Assembles the post-investigation forensics panel."""

    def build(self, state: InvestigationState) -> SearchAutopsy:
        breakdown: dict[str, int] = {}
        for call in state.tool_history:
            breakdown[call.tool] = breakdown.get(call.tool, 0) + 1
        return SearchAutopsy(
            investigation_id=state.investigation_id,
            sources_considered=list(state.metrics.sources_considered),
            candidates_retrieved=state.metrics.candidates_retrieved,
            evidence_used=len(state.evidence.items),
            evidence_rejected=state.evidence.rejected_count,
            rejection_reasons=dict(state.evidence.rejection_reasons),
            tool_calls=len(state.tool_history),
            tool_breakdown=breakdown,
            contradictions=len(state.contradictions),
            total_latency_ms=state.metrics.total_latency_ms,
            stage_latency_ms=dict(state.metrics.stage_latency_ms),
            models_used=list(state.metrics.models_used),
            gpu_peak_mb=state.metrics.gpu_peak_mb,
            claims_made=len(state.claims),
            claims_refuted=sum(
                1
                for claim in state.claims
                if claim.status in (ClaimStatus.REFUTED, ClaimStatus.CONTRADICTED)
            ),
            evidence_diversity=state.evidence.diversity(),
            degraded=state.degraded,
            degraded_reasons=list(state.degraded_reasons),
        )
