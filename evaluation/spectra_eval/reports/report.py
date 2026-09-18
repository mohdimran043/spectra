"""Render benchmark results as a research artefact, not a marketing sheet.

Every report carries a "Where SPECTRA loses" section.  A comparison that only
shows wins tells a reader nothing about when to trust the system.
"""

from __future__ import annotations

from typing import Any

HEADLINE_METRICS = (
    ("recall@10", "Recall@10"),
    ("mrr", "MRR"),
    ("ndcg@10", "nDCG@10"),
    ("entity_f1", "Entity F1"),
    ("evidence_completeness", "Evidence"),
    ("claim_support", "Claim support"),
    ("investigation_success", "Success"),
)
SPECTRA = "spectra"
# A baseline must beat SPECTRA by more than this to count as a real loss rather
# than run-to-run noise on a 3-question category.
LOSS_MARGIN = 0.02


def render_markdown(payload: dict[str, Any]) -> str:
    summary: dict[str, Any] = payload.get("summary", {})
    lines: list[str] = [
        f"# SPECTRA benchmark — suite `{payload.get('suite', 'default')}`",
        "",
        f"{payload.get('questions', 0)} questions · {len(payload.get('baselines', []))} strategies "
        f"· {payload.get('duration_seconds', 0)}s",
        "",
    ]
    lines += _environment(payload)
    lines += _headline(summary)
    lines += _cost(summary)
    lines += _calibration(summary)
    lines += _per_category(summary)
    lines += _losses(summary)
    lines += _failures(payload)
    return "\n".join(lines).rstrip() + "\n"


def _environment(payload: dict[str, Any]) -> list[str]:
    env = payload.get("environment", {})
    if not env:
        return []
    out = ["## Run environment", ""]
    if env.get("gpu_available") is False:
        out.append("> **No GPU was available for this run.** Generation and reranking ran on CPU. "
                   "Retrieval, entity-resolution and abstention figures remain "
                   "meaningful; latency figures are not comparable to a GPU run.")
        out.append("")
    models = env.get("models", {})
    if models:
        out += ["| Role | Runtime / model |", "|---|---|"]
        out += [f"| {role} | `{name}` |" for role, name in sorted(models.items())]
        out.append("")
    backends = env.get("backends", {})
    if backends:
        out.append("Backends: " + ", ".join(f"{k}=`{v}`" for k, v in sorted(backends.items())))
        out.append("")
    seed, scale = payload.get("manifest_seed"), payload.get("manifest_scale")
    if seed is not None:
        out += [f"Corpus: seed `{seed}`, scale `{scale}`.", ""]
    return out


def _headline(summary: dict[str, Any]) -> list[str]:
    if not summary:
        return []
    header = "| Strategy | " + " | ".join(label for _, label in HEADLINE_METRICS) + " |"
    divider = "|---|" + "---|" * len(HEADLINE_METRICS)
    rows = []
    for baseline, data in summary.items():
        overall = data["overall"]
        cells = " | ".join(f"{overall.get(key, 0):.3f}" for key, _ in HEADLINE_METRICS)
        rows.append(f"| `{baseline}` | {cells} |")
    return ["## Headline comparison", "", header, divider, *rows, ""]


def _cost(summary: dict[str, Any]) -> list[str]:
    if not summary:
        return []
    rows = ["## Cost and efficiency", "",
            "| Strategy | p50 latency | p95 latency | Tool calls | Claims | Degraded |",
            "|---|---|---|---|---|---|"]
    for baseline, data in summary.items():
        overall = data["overall"]
        latency = overall.get("latency_ms", {})
        rows.append(
            f"| `{baseline}` | {latency.get('p50', 0) / 1000:.2f}s | {latency.get('p95', 0) / 1000:.2f}s "
            f"| {overall.get('avg_tool_calls', 0):.1f} | {overall.get('avg_claims', 0):.1f} "
            f"| {overall.get('degraded', 0)} |"
        )
    rows.append("")
    return rows


def _calibration(summary: dict[str, Any]) -> list[str]:
    if not summary:
        return []
    rows = ["## Calibration (abstention)", "",
            "_`wrongly answered` is the dangerous column: the system asserted a conclusion "
            "the evidence does not support._", "",
            "| Strategy | correctly answered | correctly abstained | wrongly abstained | wrongly answered |",
            "|---|---|---|---|---|"]
    for baseline, data in summary.items():
        counts = data["overall"].get("abstention", {})
        rows.append(
            f"| `{baseline}` | {counts.get('correctly_answered', 0)} "
            f"| {counts.get('correctly_abstained', 0)} | {counts.get('wrongly_abstained', 0)} "
            f"| **{counts.get('wrongly_answered', 0)}** |"
        )
    rows.append("")
    return rows


def _per_category(summary: dict[str, Any]) -> list[str]:
    categories = sorted({c for data in summary.values() for c in data.get("by_category", {})})
    if not categories:
        return []
    baselines = list(summary)
    rows = ["## Investigation success by category", "",
            "| Category | " + " | ".join(f"`{b}`" for b in baselines) + " |",
            "|---|" + "---|" * len(baselines)]
    for category in categories:
        cells = []
        for baseline in baselines:
            data = summary[baseline].get("by_category", {}).get(category)
            cells.append(f"{data['investigation_success']:.2f}" if data else "—")
        rows.append(f"| {category} | " + " | ".join(cells) + " |")
    rows.append("")
    return rows


def _losses(summary: dict[str, Any]) -> list[str]:
    """Where a simpler strategy matched or beat SPECTRA."""
    if SPECTRA not in summary:
        return []
    out = ["## Where SPECTRA loses", ""]
    spectra_cats = summary[SPECTRA].get("by_category", {})
    findings: list[str] = []

    for baseline, data in summary.items():
        if baseline == SPECTRA:
            continue
        for category, stats in data.get("by_category", {}).items():
            mine = spectra_cats.get(category)
            if not mine:
                continue
            delta = stats["investigation_success"] - mine["investigation_success"]
            if delta > LOSS_MARGIN:
                findings.append(
                    f"- **{category}** — `{baseline}` scores {stats['investigation_success']:.2f} "
                    f"vs SPECTRA's {mine['investigation_success']:.2f} (+{delta:.2f})."
                )

    spectra_overall = summary[SPECTRA]["overall"]
    latency = spectra_overall.get("latency_ms", {})
    cheapest = min(
        ((b, d["overall"].get("latency_ms", {}).get("p50", 0.0)) for b, d in summary.items()),
        key=lambda pair: pair[1],
        default=None,
    )
    if cheapest and cheapest[0] != SPECTRA and cheapest[1] > 0:
        factor = latency.get("p50", 0.0) / cheapest[1]
        findings.append(
            f"- **Latency** — SPECTRA's median is {factor:.1f}x `{cheapest[0]}`'s "
            f"({latency.get('p50', 0) / 1000:.2f}s vs {cheapest[1] / 1000:.2f}s)."
        )
    if spectra_overall.get("wrongly_answered", 0):
        findings.append(
            f"- **Calibration** — SPECTRA answered {spectra_overall['wrongly_answered']} question(s) "
            "it should have abstained on."
        )
    if spectra_overall.get("errors", 0):
        findings.append(f"- **Reliability** — {spectra_overall['errors']} question(s) errored.")

    out += findings or ["- No category in this run where a simpler strategy beat SPECTRA by "
                        f"more than {LOSS_MARGIN:.2f}."]
    out.append("")
    return out


def _failures(payload: dict[str, Any]) -> list[str]:
    errored = [s for s in payload.get("scores", []) if s.get("error")]
    if not errored:
        return []
    out = ["## Errors", "", "| Strategy | Question | Error |", "|---|---|---|"]
    out += [f"| `{s['baseline']}` | {s['question_id']} | {s['error']} |" for s in errored[:25]]
    out.append("")
    return out
