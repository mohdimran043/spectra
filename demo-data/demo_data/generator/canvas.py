"""Drawing primitives for the generated screenshots and diagrams.

Text is drawn with a real TrueType font at readable sizes so a real OCR engine
has something to read.  Every string drawn is also recorded with its bounding
box, which is what the ``.render.json`` sidecar publishes as ground truth.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from PIL import Image, ImageDraw, ImageFont

from .constants import BOLD_FONT_CANDIDATES, FONT_CANDIDATES, MONO_FONT_CANDIDATES

BACKGROUND: Final[tuple[int, int, int]] = (18, 22, 30)
PANEL: Final[tuple[int, int, int]] = (28, 34, 46)
PANEL_ALT: Final[tuple[int, int, int]] = (36, 43, 58)
BORDER: Final[tuple[int, int, int]] = (74, 86, 110)
TEXT: Final[tuple[int, int, int]] = (226, 232, 240)
MUTED: Final[tuple[int, int, int]] = (148, 163, 184)
ACCENT: Final[tuple[int, int, int]] = (56, 160, 235)
DANGER: Final[tuple[int, int, int]] = (239, 96, 96)
SUCCESS: Final[tuple[int, int, int]] = (74, 201, 140)
WARNING: Final[tuple[int, int, int]] = (233, 176, 74)

TITLE_SIZE: Final[int] = 30
HEADING_SIZE: Final[int] = 22
BODY_SIZE: Final[int] = 18
SMALL_SIZE: Final[int] = 15
ROW_HEIGHT: Final[int] = 34


class FontUnavailableError(RuntimeError):
    """Raised when no usable TrueType font is installed."""


def _load(candidates: Sequence[str], size: int) -> ImageFont.FreeTypeFont:
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size)
    raise FontUnavailableError(f"none of the configured fonts exist: {list(candidates)}")


@dataclass(frozen=True)
class DrawnText:
    """One string as it was rendered, with the box OCR should find it in."""

    text: str
    box: tuple[int, int, int, int]
    role: str


class Sheet:
    """A drawing surface that remembers every string it painted."""

    def __init__(self, width: int, height: int, background: tuple[int, int, int] = BACKGROUND) -> None:
        self._image = Image.new("RGB", (width, height), background)
        self._draw = ImageDraw.Draw(self._image)
        self._texts: list[DrawnText] = []
        self.width = width
        self.height = height

    # -- text -------------------------------------------------------------
    def text(
        self,
        position: tuple[int, int],
        value: str,
        *,
        size: int = BODY_SIZE,
        colour: tuple[int, int, int] = TEXT,
        bold: bool = False,
        mono: bool = False,
        role: str = "label",
    ) -> tuple[int, int, int, int]:
        candidates = MONO_FONT_CANDIDATES if mono else (BOLD_FONT_CANDIDATES if bold else FONT_CANDIDATES)
        font = _load(candidates, size)
        self._draw.text(position, value, font=font, fill=colour)
        left, top, right, bottom = self._draw.textbbox(position, value, font=font)
        box = (int(left), int(top), int(right), int(bottom))
        self._texts.append(DrawnText(text=value, box=box, role=role))
        return box

    # -- shapes -----------------------------------------------------------
    def panel(self, box: tuple[int, int, int, int], fill: tuple[int, int, int] = PANEL) -> None:
        self._draw.rectangle(box, fill=fill, outline=BORDER, width=2)

    def line(self, start: tuple[int, int], end: tuple[int, int], colour: tuple[int, int, int] = BORDER,
             width: int = 2) -> None:
        self._draw.line([start, end], fill=colour, width=width)

    def polyline(self, points: Sequence[tuple[int, int]], colour: tuple[int, int, int] = ACCENT,
                 width: int = 3) -> None:
        self._draw.line(list(points), fill=colour, width=width)

    def arrow(self, start: tuple[int, int], end: tuple[int, int], colour: tuple[int, int, int] = MUTED) -> None:
        self.line(start, end, colour=colour, width=2)
        head = 7
        self._draw.polygon(
            [(end[0], end[1]), (end[0] - head, end[1] - head), (end[0] - head, end[1] + head)], fill=colour
        )

    def node(
        self,
        box: tuple[int, int, int, int],
        label: str,
        sublabel: str = "",
        *,
        accent: tuple[int, int, int] = ACCENT,
        role: str = "node",
    ) -> None:
        self._draw.rectangle(box, fill=PANEL_ALT, outline=accent, width=3)
        self.text((box[0] + 14, box[1] + 12), label, size=BODY_SIZE, bold=True, role=role)
        if sublabel:
            self.text((box[0] + 14, box[1] + 40), sublabel, size=SMALL_SIZE, colour=MUTED, role=role)

    def table(
        self,
        origin: tuple[int, int],
        headers: Sequence[str],
        rows: Sequence[Sequence[str]],
        widths: Sequence[int],
        *,
        highlight_row: int | None = None,
    ) -> None:
        x, y = origin
        cursor = x
        for header, width in zip(headers, widths, strict=True):
            self.text((cursor, y), header, size=SMALL_SIZE, colour=MUTED, bold=True, role="header")
            cursor += width
        for index, row in enumerate(rows):
            top = y + ROW_HEIGHT * (index + 1)
            if index == highlight_row:
                self._draw.rectangle(
                    (x - 8, top - 6, x + sum(widths) + 8, top + ROW_HEIGHT - 10), fill=(58, 30, 34)
                )
            cursor = x
            for value, width in zip(row, widths, strict=False):
                colour = DANGER if value in {"failed", "FAILED", "DECLINED"} else TEXT
                self.text((cursor, top), value, size=SMALL_SIZE, colour=colour, mono=True, role="cell")
                cursor += width

    def chart(
        self,
        box: tuple[int, int, int, int],
        series: Sequence[float],
        *,
        colour: tuple[int, int, int] = ACCENT,
    ) -> None:
        self.panel(box, fill=PANEL_ALT)
        if len(series) < 2:
            return
        left, top, right, bottom = box
        peak = max(series) or 1.0
        step = (right - left - 24) / (len(series) - 1)
        points = [
            (int(left + 12 + step * index), int(bottom - 12 - (value / peak) * (bottom - top - 28)))
            for index, value in enumerate(series)
        ]
        self.polyline(points, colour=colour)

    # -- output -----------------------------------------------------------
    def save(self, path: Path) -> tuple[DrawnText, ...]:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._image.save(path, format="PNG", optimize=False)
        return tuple(self._texts)

    @property
    def drawn(self) -> tuple[DrawnText, ...]:
        return tuple(self._texts)
