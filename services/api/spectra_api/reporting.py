"""Render an investigation as a shareable case report.

Presentation only - every value comes from the structured ``InvestigationAnswer``,
so the report can never assert something the evidence ledger does not contain.
"""

from __future__ import annotations

from spectra_schemas import InvestigationAnswer, format_timestamp

STATUS_LABEL = {
    "supported": "Supported",
    "partially_supported": "Partially supported",
    "contested": "Contested",
    "insufficient_evidence": "Insufficient evidence",
    "degraded": "Degraded",
    "failed": "Failed",
}


def render_markdown(answer: InvestigationAnswer) -> str:
    lines: list[str] = [
        f"# Investigation {answer.investigation_id}",
        "",
        f"**Status:** {STATUS_LABEL.get(answer.status.value, answer.status.value)}  ",
        f"**Confidence:** {answer.confidence_label.value.title()} ({answer.confidence:.0%})",
        "",
    ]
    if answer.degraded:
        lines += ["> **Degraded run.** " + "; ".join(answer.degraded_reasons), ""]

    lines += ["## Conclusion", "", answer.answer.strip() or "_No conclusion was reached._", ""]

    lines += _claims(answer)
    lines += _evidence(answer)
    lines += _contradictions(answer)
    lines += _timeline(answer)
    lines += _links(answer)
    lines += _why(answer)
    lines += _autopsy(answer)
    return "\n".join(lines).rstrip() + "\n"


def _claims(answer: InvestigationAnswer) -> list[str]:
    """Each claim is judged on its own evidence, so confidences do not sum to 1."""
    if not answer.claims:
        return []
    out = [
        "## Claims",
        "",
        "| # | Statement | Status | Confidence | For | Against |",
        "|---|---|---|---|---|---|",
    ]
    for claim in answer.claims:
        out.append(
            f"| {claim.claim_id} | {claim.text} | {claim.status.value} | {claim.confidence:.0%} "
            f"| {len(claim.supporting_evidence)} | {len(claim.contradicting_evidence)} |"
        )
    out.append("")
    probed = [c for c in answer.claims if c.disproof_probe]
    if probed:
        out += ["### What was searched for to refute this", ""]
        out += [f"- **{c.claim_id}** — {c.disproof_probe}" for c in probed]
        out.append("")
    return out


def _evidence(answer: InvestigationAnswer) -> list[str]:
    if not answer.evidence:
        return []
    out = ["## Evidence ledger", ""]
    for item in answer.evidence:
        label = item.get("label", "")
        out += [
            f"**[{label}] {item.get('citation', '')}**  ",
            f"{item.get('summary', '')}  ",
            f"_stance: {item.get('stance', 'neutral')} · relevance {float(item.get('relevance', 0)):.2f} "
            f"· reliability {float(item.get('reliability', 0)):.2f} — {item.get('reliability_reason', '')}_",
            "",
        ]
    return out


def _contradictions(answer: InvestigationAnswer) -> list[str]:
    if not answer.contradictions:
        return []
    out = ["## Contradictions", ""]
    for c in answer.contradictions:
        out.append(f"- **{c.statement}** ({c.kind}, severity {c.severity:.2f})")
        if c.detail:
            out.append(f"  - {c.detail}")
        out.append(f"  - Resolution: {c.resolution or 'unresolved — both sides stand'}")
    out.append("")
    return out


def _timeline(answer: InvestigationAnswer) -> list[str]:
    if not answer.timeline:
        return []
    out = ["## Timeline", ""]
    for event in answer.timeline:
        out.append(f"- `{event.occurred_at.isoformat()}` **{event.label}**"
                   + (f" — {event.detail}" if event.detail else ""))
    out.append("")
    return out


def _links(answer: InvestigationAnswer) -> list[str]:
    if not answer.application_links:
        return []
    out = ["## Application records", ""]
    for link in answer.application_links:
        verified = "verified" if link.verified_in_database else "unverified"
        out.append(f"- [{link.label} — {link.record_id}]({link.url}) ({verified})")
    out.append("")
    return out


def _why(answer: InvestigationAnswer) -> list[str]:
    explanation = answer.explanation
    if not explanation.reasons and not explanation.sources_skipped:
        return []
    out = ["## Why these sources were searched", ""]
    out += [f"- {reason}" for reason in explanation.reasons]
    for skipped in explanation.sources_skipped:
        out.append(f"- _Skipped {skipped.get('source', '?')}: {skipped.get('reason', '')}_")
    out.append("")
    return out


def _autopsy(answer: InvestigationAnswer) -> list[str]:
    a = answer.autopsy
    if a is None:
        return []
    return [
        "## Search autopsy",
        "",
        f"- Sources considered: {', '.join(a.sources_considered) or 'none'}",
        f"- Candidates retrieved: {a.candidates_retrieved}",
        f"- Evidence used / rejected: {a.evidence_used} / {a.evidence_rejected}",
        f"- Tool calls: {a.tool_calls}",
        f"- Claims made / refuted: {a.claims_made} / {a.claims_refuted}",
        f"- Contradictions: {a.contradictions}",
        f"- Evidence diversity: {a.evidence_diversity:.2f}",
        f"- Total latency: {a.total_latency_ms / 1000:.1f}s",
        f"- Models used: {', '.join(a.models_used) or 'none'}",
        "",
    ]


__all__ = ["render_markdown", "format_timestamp"]
