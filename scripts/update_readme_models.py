#!/usr/bin/env python
"""Splice the measured model table into README.md.

Keeps the published numbers honest: they come from
`scripts/model_benchmark.py`'s JSON output, not from memory. Re-run both after
any model or hardware change.

    .venv/bin/python scripts/model_benchmark.py
    .venv/bin/python scripts/update_readme_models.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from spectra_config import REPO_ROOT

BEGIN = "<!-- BEGIN:model-table -->"
END = "<!-- END:model-table -->"

ROLE_LABEL = {
    "deep_brain": "Deep brain",
    "fast_brain": "Fast brain",
    "vision": "Vision",
    "embedding": "Text embedding",
    "mm_embedding": "Multimodal embedding",
    "reranker": "Reranker",
    "speech": "Speech (ASR)",
    "ocr": "OCR",
}
ROLE_ORDER = tuple(ROLE_LABEL)
ROLE_PURPOSE = {
    "deep_brain": "Planning, hypotheses, synthesis",
    "fast_brain": "Routing, classification, cheap answers",
    "vision": "Captioning images and keyframes",
    "embedding": "Dense text retrieval",
    "mm_embedding": "Shared text/image space",
    "reranker": "Precision over the top-K",
    "speech": "Transcription with timestamps",
    "ocr": "Text out of images",
}
# Which pipeline each role serves - the distinction the architecture is built on.
ROLE_PHASE = {
    "deep_brain": "query",
    "fast_brain": "query",
    "vision": "ingest",
    "embedding": "both",
    "mm_embedding": "ingest",
    "reranker": "query",
    "speech": "ingest",
    "ocr": "ingest",
}
PHASE_MARK = {"ingest": "ingest", "query": "query", "both": "both"}


def _duration(ms: float) -> str:
    if ms <= 0:
        return "—"
    if ms >= 1000:
        return f"{ms / 1000:.2f} s"
    return f"{ms:.0f} ms"


def render(payload: dict) -> str:
    gpu = payload.get("gpu", {})
    by_role = {row["role"]: row for row in payload.get("results", [])}

    hardware = gpu.get("name") or "CPU only"
    driver = f", driver {gpu['driver']}" if gpu.get("driver") else ""
    budget = f"{gpu['budget_mb'] / 1024:.0f} GB usable" if gpu.get("budget_mb") else "no VRAM budget"

    lines = [
        BEGIN,
        f"Measured on **{hardware}**{driver} · profile `{payload.get('profile', '?')}` · {budget}.",
        "Reproduce with `.venv/bin/python scripts/model_benchmark.py`.",
        "",
        "| Role | Model | Runtime | Device | VRAM | Cold load | Warm call | Workload | Pipeline |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for role in ROLE_ORDER:
        row = by_role.get(role)
        if row is None:
            continue
        if row.get("error"):
            lines.append(
                f"| **{ROLE_LABEL[role]}** | `{row.get('model') or '—'}` | {row.get('runtime') or '—'} "
                f"| — | — | — | _unavailable_ | {row.get('unit', '')} | {PHASE_MARK[ROLE_PHASE[role]]} |"
            )
            continue
        vram = f"{row['declared_vram_mb'] / 1024:.1f} GB" if row["declared_vram_mb"] else "CPU"
        load = f"{row['load_seconds']:.1f} s" if row.get("load_seconds") is not None else "—"
        lines.append(
            f"| **{ROLE_LABEL[role]}** | `{row['model']}` | {row['runtime']} | {row['device']} "
            f"| {vram} | {load} | **{_duration(row['median_ms'])}** | {row['unit']} "
            f"| {PHASE_MARK[ROLE_PHASE[role]]} |"
        )

    total = sum(r.get("declared_vram_mb", 0) for r in by_role.values())
    lines += [
        "",
        "*Cold load* is first use, including any download already cached. *Warm call* is the median of "
        "three runs after warm-up.",
        "",
        f"The declared VRAM totals **{total / 1024:.1f} GB** against a **{budget}** budget, which is why "
        "model residency is scheduled rather than assumed: roles are loaded on demand, evicted "
        "least-recently-used, and at most one heavyweight model is cuda-resident at a time. "
        "Watch it happen on the `/models` page during a deep investigation.",
        "",
        "Roles marked `ingest` run **only** on the ingestion path and are refused at query time — see "
        "[Two pipelines](docs/architecture.md#2-two-pipelines-deliberately-separated).",
        END,
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Update the README model table")
    parser.add_argument("--json", type=Path, default=Path("/tmp/spectra-model-benchmark.json"))
    parser.add_argument("--readme", type=Path, default=REPO_ROOT / "README.md")
    args = parser.parse_args()

    payload = json.loads(args.json.read_text())
    table = render(payload)
    text = args.readme.read_text()

    if BEGIN in text and END in text:
        head, _, rest = text.partition(BEGIN)
        _, _, tail = rest.partition(END)
        args.readme.write_text(head + table + tail)
    else:
        print(f"markers {BEGIN} / {END} not found in {args.readme}")
        return 1
    print(f"updated {args.readme} with {len(payload.get('results', []))} measured roles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
