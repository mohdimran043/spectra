"""RapidOCR - the PP-OCR models served through ONNX Runtime.

Chosen as the default OCR engine because it is pip-installable and needs no
system packages, so `pip install` alone gives SPECTRA working text extraction on
any host.  It runs the same PP-OCR detection + recognition models as PaddleOCR.
"""

from __future__ import annotations

import asyncio
import importlib.util
import time
from typing import Any

from spectra_config.logging import get_logger

from ..interfaces import OCRLine, OCRProvider, OCRResult
from .imaging import open_image

log = get_logger(__name__)

RAPIDOCR_RUNTIME = "rapidocr"
RAPIDOCR_PACKAGE = "rapidocr_onnxruntime"
MIN_CONFIDENCE = 0.0


class RapidOCRProvider(OCRProvider):
    """PP-OCR detection + recognition via ONNX Runtime, imported lazily."""

    runtime_name = RAPIDOCR_RUNTIME

    def __init__(self, model: str = "PP-OCRv4", device: str = "auto", **options: Any) -> None:
        super().__init__(model, device, **options)
        self._engine: Any | None = None

    async def available(self) -> tuple[bool, str]:
        if importlib.util.find_spec(RAPIDOCR_PACKAGE) is None:
            return False, f"the {RAPIDOCR_PACKAGE} package is not installed"
        return True, f"{RAPIDOCR_PACKAGE} is installed"

    async def load(self) -> None:
        if self._engine is not None:
            self._loaded = True
            return
        self._engine = await asyncio.to_thread(self._build_engine)
        self._loaded = True
        log.info("ocr.loaded", runtime=self.runtime_name, model=self.model)

    def _build_engine(self) -> Any:
        from rapidocr_onnxruntime import RapidOCR

        return RapidOCR()

    async def unload(self) -> None:
        self._engine = None
        self._loaded = False

    async def read(self, image_bytes: bytes) -> OCRResult:
        started = time.perf_counter()
        if self._engine is None:
            await self.load()
        try:
            lines = await asyncio.to_thread(self._run, image_bytes)
        except Exception as exc:
            log.warning("ocr.failed", runtime=self.runtime_name, error=str(exc))
            return OCRResult(
                lines=[],
                engine=self.runtime_name,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                degraded=True,
                degraded_reason=f"{self.runtime_name} failed to read the image: {exc}",
            )
        return OCRResult(
            lines=lines,
            engine=self.runtime_name,
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )

    def _run(self, image_bytes: bytes) -> list[OCRLine]:
        import numpy as np

        image = open_image(image_bytes).convert("RGB")
        result, _elapsed = self._engine(np.array(image))
        return [line for line in (_to_line(entry) for entry in (result or [])) if line is not None]


def _to_line(entry: Any) -> OCRLine | None:
    """RapidOCR yields ``[box, text, confidence]`` per detected line."""
    try:
        box, text, confidence = entry[0], str(entry[1]), float(entry[2])
    except (IndexError, TypeError, ValueError):
        return None
    if not text.strip():
        return None
    return OCRLine(text=text, confidence=max(confidence, MIN_CONFIDENCE), bbox=_to_bbox(box))


def _to_bbox(box: Any) -> tuple[float, float, float, float] | None:
    """Collapse the four detected corners into an axis-aligned box."""
    try:
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
    except (IndexError, TypeError, ValueError):
        return None
    if not xs or not ys:
        return None
    return (min(xs), min(ys), max(xs), max(ys))
