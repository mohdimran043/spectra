"""OCR providers: PaddleOCR (optional) and Tesseract (python binding or binary)."""

from __future__ import annotations

import asyncio
import importlib.util
import shutil
import subprocess
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from spectra_config.logging import get_logger

from ..interfaces import OCRLine, OCRProvider, OCRResult
from .imaging import open_image

log = get_logger(__name__)

PADDLE_RUNTIME = "paddleocr"
TESSERACT_RUNTIME = "tesseract"
PYTESSERACT_PACKAGE = "pytesseract"
TESSERACT_BINARY = "tesseract"
DEFAULT_LANGUAGE = "en"
TESSERACT_LANGUAGE = "eng"
BINARY_TIMEOUT_SECONDS = 60
TSV_COLUMN_COUNT = 12
MIN_CONFIDENCE = 0.0
CONFIDENCE_SCALE = 100.0


class PaddleOCRProvider(OCRProvider):
    """PP-OCR text detection + recognition.  Optional dependency, imported lazily."""

    runtime_name = PADDLE_RUNTIME

    def __init__(self, model: str = "PP-OCRv4", device: str = "auto", **options: Any) -> None:
        super().__init__(model, device, **options)
        self.language = str(options.get("language") or DEFAULT_LANGUAGE)
        self._engine: Any | None = None

    async def available(self) -> tuple[bool, str]:
        if importlib.util.find_spec(PADDLE_RUNTIME) is None:
            return False, f"{PADDLE_RUNTIME} package is not installed"
        return True, f"{PADDLE_RUNTIME} available for {self.model}"

    async def load(self) -> None:
        if self._engine is not None:
            return
        ok, reason = await self.available()
        if not ok:
            raise RuntimeError(f"cannot load PaddleOCR: {reason}")
        self._engine = await asyncio.to_thread(self._construct)
        await super().load()

    def _construct(self) -> Any:
        from paddleocr import PaddleOCR

        return PaddleOCR(use_angle_cls=True, lang=self.language, use_gpu=self.device == "cuda")

    async def unload(self) -> None:
        self._engine = None
        await super().unload()

    async def read(self, image_bytes: bytes) -> OCRResult:
        await self.load()
        started = time.perf_counter()
        lines = await asyncio.to_thread(self._recognise, image_bytes)
        return OCRResult(
            lines=lines,
            engine=f"{PADDLE_RUNTIME}:{self.model}",
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )

    def _recognise(self, image_bytes: bytes) -> list[OCRLine]:
        import numpy as np

        engine = self._engine
        if engine is None:  # pragma: no cover - load() raises first
            raise RuntimeError("PaddleOCR is not loaded")
        array = np.asarray(open_image(image_bytes).convert("RGB"))
        raw = engine.ocr(array, cls=True)
        return _parse_paddle(raw)


def _parse_paddle(raw: Any) -> list[OCRLine]:
    """PaddleOCR returns ``[[[box], (text, confidence)], ...]`` per page."""
    lines: list[OCRLine] = []
    for page in raw or []:
        for entry in page or []:
            parsed = _parse_paddle_entry(entry)
            if parsed is not None:
                lines.append(parsed)
    return lines


def _parse_paddle_entry(entry: Any) -> OCRLine | None:
    if not isinstance(entry, (list, tuple)) or len(entry) < 2:
        return None
    box, payload = entry[0], entry[1]
    if not isinstance(payload, (list, tuple)) or not payload:
        return None
    text = str(payload[0])
    confidence = float(payload[1]) if len(payload) > 1 else 1.0
    return OCRLine(text=text, confidence=confidence, bbox=_box_to_bbox(box))


def _box_to_bbox(box: Any) -> tuple[float, float, float, float] | None:
    try:
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
    except (TypeError, ValueError, IndexError):
        return None
    return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


class TesseractOCRProvider(OCRProvider):
    """Tesseract via ``pytesseract`` when installed, otherwise the CLI binary."""

    runtime_name = TESSERACT_RUNTIME

    def __init__(self, model: str = TESSERACT_BINARY, device: str = "cpu", **options: Any) -> None:
        super().__init__(model, device, **options)
        self.language = str(options.get("language") or TESSERACT_LANGUAGE)

    def _binary(self) -> str | None:
        return shutil.which(TESSERACT_BINARY)

    def _has_binding(self) -> bool:
        return importlib.util.find_spec(PYTESSERACT_PACKAGE) is not None

    async def available(self) -> tuple[bool, str]:
        if self._has_binding():
            return True, f"{PYTESSERACT_PACKAGE} binding present"
        binary = self._binary()
        if binary:
            return True, f"{TESSERACT_BINARY} binary at {binary}"
        return False, f"neither the {PYTESSERACT_PACKAGE} package nor a {TESSERACT_BINARY} binary is present"

    async def read(self, image_bytes: bytes) -> OCRResult:
        ok, reason = await self.available()
        if not ok:
            raise RuntimeError(f"tesseract unavailable: {reason}")
        started = time.perf_counter()
        tsv = await asyncio.to_thread(self._run, image_bytes)
        return OCRResult(
            lines=_parse_tsv(tsv),
            engine=TESSERACT_RUNTIME,
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )

    def _run(self, image_bytes: bytes) -> str:
        if self._has_binding():
            import pytesseract

            return str(
                pytesseract.image_to_data(open_image(image_bytes), lang=self.language, config="--psm 3")
            )
        return self._run_binary(image_bytes)

    def _run_binary(self, image_bytes: bytes) -> str:
        binary = self._binary()
        if binary is None:  # pragma: no cover - available() guards this
            raise RuntimeError(f"{TESSERACT_BINARY} binary disappeared")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "page.png"
            open_image(image_bytes).save(source)
            completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
                [binary, str(source), "stdout", "-l", self.language, "tsv"],
                capture_output=True,
                text=True,
                timeout=BINARY_TIMEOUT_SECONDS,
                check=False,
            )
        if completed.returncode != 0:
            raise RuntimeError(f"{TESSERACT_BINARY} exited {completed.returncode}: {completed.stderr.strip()}")
        return completed.stdout


def _parse_tsv(tsv: str) -> list[OCRLine]:
    """Group Tesseract word rows back into lines, averaging their confidences."""
    rows = [row.split("\t") for row in tsv.splitlines()[1:] if row.strip()]
    grouped: dict[tuple[str, str, str], list[list[str]]] = defaultdict(list)
    for row in rows:
        if len(row) < TSV_COLUMN_COUNT or not row[-1].strip():
            continue
        grouped[(row[2], row[3], row[4])].append(row)
    return [line for line in (_tsv_line(words) for words in grouped.values()) if line is not None]


def _tsv_line(words: list[list[str]]) -> OCRLine | None:
    text = " ".join(word[-1].strip() for word in words).strip()
    if not text:
        return None
    confidences = [float(word[10]) for word in words if _is_number(word[10])]
    lefts = [float(word[6]) for word in words if _is_number(word[6])]
    tops = [float(word[7]) for word in words if _is_number(word[7])]
    rights = [float(word[6]) + float(word[8]) for word in words if _is_number(word[8])]
    bottoms = [float(word[7]) + float(word[9]) for word in words if _is_number(word[9])]
    confidence = max(MIN_CONFIDENCE, sum(confidences) / len(confidences) / CONFIDENCE_SCALE) if confidences else 1.0
    bbox = (min(lefts), min(tops), max(rights) - min(lefts), max(bottoms) - min(tops)) if lefts else None
    return OCRLine(text=text, confidence=round(confidence, 4), bbox=bbox)


def _is_number(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True
