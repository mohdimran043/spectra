#!/usr/bin/env python
"""Measure every model role: cold load, warm inference, and VRAM cost.

Produces the table published in the README.  Numbers are measured on this host,
not estimated, and the script is committed so they can be reproduced or refuted:

    .venv/bin/python scripts/model_benchmark.py
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import time
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path

from spectra_ai_core import ChatMessage, get_gateway
from spectra_ai_core.gpu import detect_gpu
from spectra_ai_core.phase import ingestion_phase
from spectra_config import get_settings
from spectra_schemas import ModelRole

WARMUP_RUNS = 1
TIMED_RUNS = 3
SAMPLE_RATE = 16_000
TONE_SECONDS = 3.0

EVIDENCE_PROMPT = (
    "EVIDENCE\n"
    "[E1] Database: transaction TX82931 status=FAILED failure_reason=auth_timeout.\n"
    "[E2] Incident INC1829 root cause: authentication service connection pool exhausted.\n"
    "[E3] Meeting 00:42:17: 'the auth service was unavailable for about four minutes'.\n\n"
    "Why did TX82931 fail? Two sentences, cite with [E#] tags."
)
RERANK_DOCS = [
    "The authentication service timed out while validating the session token.",
    "Quarterly revenue summary for the retail segment.",
    "Capacity planning notes for the reporting cluster.",
    "The payment gateway held the authorisation session open until the pool drained.",
]


@dataclass
class RoleResult:
    role: str
    runtime: str = ""
    model: str = ""
    device: str = ""
    declared_vram_mb: int = 0
    load_seconds: float | None = None
    latency_ms: list[float] = field(default_factory=list)
    unit: str = ""
    throughput: str = ""
    note: str = ""
    error: str | None = None

    @property
    def median_ms(self) -> float:
        if not self.latency_ms:
            return 0.0
        ordered = sorted(self.latency_ms)
        return round(ordered[len(ordered) // 2], 1)


def _png(text: str = "TX82931") -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (640, 200), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 34)
    except OSError:  # pragma: no cover - font-dependent
        font = ImageFont.load_default()
    draw.text((30, 40), "Payment Gateway Console", fill="black", font=font)
    draw.text((30, 110), f"Transaction: {text}", fill="black", font=font)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def _wav(path: Path) -> Path:
    import math
    import struct

    frames = int(SAMPLE_RATE * TONE_SECONDS)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(
            b"".join(
                struct.pack("<h", int(12000 * math.sin(2 * math.pi * 220 * n / SAMPLE_RATE)))
                for n in range(frames)
            )
        )
    return path


async def _timed(operation, runs: int = TIMED_RUNS) -> list[float]:
    samples: list[float] = []
    for _ in range(runs):
        started = time.perf_counter()
        await operation()
        samples.append((time.perf_counter() - started) * 1000.0)
    return samples


async def _measure(gateway, role: ModelRole, operation, unit: str, note: str = "") -> RoleResult:
    status = await gateway.status()
    info = next((m for m in status.models if m.role is role), None)
    result = RoleResult(
        role=role.value,
        runtime=(info.active_runtime or "") if info else "",
        model=(info.active_model or "") if info else "",
        device=(info.device or "") if info else "",
        declared_vram_mb=info.vram_mb if info else 0,
        unit=unit,
        note=note,
    )
    try:
        cold = time.perf_counter()
        await operation()
        result.load_seconds = round(time.perf_counter() - cold, 2)
        for _ in range(WARMUP_RUNS):
            await operation()
        result.latency_ms = await _timed(operation)
    except Exception as exc:  # noqa: BLE001 - recorded, not raised
        result.error = f"{type(exc).__name__}: {exc}"
    return result


async def run() -> dict:
    settings = get_settings()
    gpu = detect_gpu(settings)
    gateway = await get_gateway()
    image = _png()
    audio = _wav(Path("/tmp/spectra-bench-tone.wav"))
    results: list[RoleResult] = []

    async def embed():
        await gateway.embed_texts(["why did transaction TX82931 fail"], is_query=True)

    results.append(await _measure(gateway, ModelRole.EMBEDDING, embed, "1 short query"))

    async def rerank():
        await gateway.rerank("authentication timeout", RERANK_DOCS)

    results.append(await _measure(gateway, ModelRole.RERANKER, rerank, f"{len(RERANK_DOCS)} pairs"))

    async def mm_embed():
        async with ingestion_phase():
            await gateway.embed_images([image])

    results.append(await _measure(gateway, ModelRole.MM_EMBEDDING, mm_embed, "1 image"))

    async def ocr():
        async with ingestion_phase():
            await gateway.ocr(image)

    results.append(await _measure(gateway, ModelRole.OCR, ocr, "1 screenshot"))

    async def transcribe():
        async with ingestion_phase():
            await gateway.transcribe(str(audio))

    results.append(
        await _measure(gateway, ModelRole.SPEECH, transcribe, f"{TONE_SECONDS:.0f}s audio")
    )

    async def vision():
        async with ingestion_phase():
            await gateway.describe_image(image, "Describe this screenshot.")

    results.append(await _measure(gateway, ModelRole.VISION, vision, "1 image caption"))

    messages = [
        ChatMessage(role="system", content="You are an evidence analyst. Cite with [E#] tags."),
        ChatMessage(role="user", content=EVIDENCE_PROMPT),
    ]

    async def fast():
        await gateway.generate(messages, role=ModelRole.FAST_BRAIN, max_tokens=200, temperature=0.1)

    results.append(await _measure(gateway, ModelRole.FAST_BRAIN, fast, "~60 output tokens"))

    async def deep():
        await gateway.generate(messages, role=ModelRole.DEEP_BRAIN, max_tokens=320, temperature=0.2)

    results.append(await _measure(gateway, ModelRole.DEEP_BRAIN, deep, "~300 output tokens"))

    final = await gateway.status()
    return {
        "gpu": {
            "available": gpu.available,
            "name": gpu.name,
            "total_mb": gpu.total_mb,
            "budget_mb": gpu.budget_mb,
            "driver": gpu.driver_version,
            "detail": gpu.detail,
        },
        "profile": final.profile,
        "degraded": final.degraded,
        "degraded_reasons": final.degraded_reasons,
        "results": [asdict(r) | {"median_ms": r.median_ms} for r in results],
    }


def render_markdown(payload: dict) -> str:
    gpu = payload["gpu"]
    header = (
        f"Measured on {gpu.get('name') or 'CPU only'}"
        + (f" (driver {gpu['driver']})" if gpu.get("driver") else "")
        + f", profile `{payload['profile']}`."
    )
    lines = [
        header,
        "",
        "| Role | Runtime | Model | Device | VRAM | Cold load | Warm latency | Workload |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in payload["results"]:
        if row.get("error"):
            lines.append(
                f"| `{row['role']}` | {row['runtime']} | {row['model']} | {row['device']} "
                f"| — | — | _{row['error'][:40]}_ | {row['unit']} |"
            )
            continue
        vram = f"{row['declared_vram_mb'] / 1024:.1f} GB" if row["declared_vram_mb"] else "CPU"
        load = f"{row['load_seconds']:.1f} s" if row["load_seconds"] is not None else "—"
        median = row["median_ms"]
        warm = f"{median / 1000:.2f} s" if median >= 1000 else f"{median:.0f} ms"
        lines.append(
            f"| `{row['role']}` | {row['runtime']} | `{row['model']}` | {row['device']} "
            f"| {vram} | {load} | **{warm}** | {row['unit']} |"
        )
    return "\n".join(lines)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark every SPECTRA model role")
    parser.add_argument("--json", type=Path, default=Path("/tmp/spectra-model-benchmark.json"))
    args = parser.parse_args()

    payload = await run()
    args.json.write_text(json.dumps(payload, indent=2))
    print(render_markdown(payload))
    print(f"\nraw: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
