"""Shared vocabulary for every content extractor.

An extractor turns one source file into an ordered list of ``ExtractedBlock``.
Blocks are deliberately *pre-chunking*: they keep the smallest unit the parser
could see (a paragraph, a heading, a table, a caption) together with the
provenance that unit was found at.  ``chunking.chunk_blocks`` then packs blocks
into retrievable chunks without ever losing the page / section / bbox of the
first contributing block.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal

BlockKind = Literal["paragraph", "heading", "table", "caption", "ocr", "code"]

BBox = tuple[float, float, float, float]

#: Blocks that become a chunk of their own rather than being packed with others.
STANDALONE_KINDS: frozenset[str] = frozenset({"table"})


@dataclass(frozen=True)
class ExtractedBlock:
    """One unit of extracted content with the provenance it was found at."""

    text: str
    kind: BlockKind = "paragraph"
    page: int | None = None
    section: str | None = None
    ordinal: int = 0
    bbox: BBox | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def with_ordinal(self, ordinal: int) -> ExtractedBlock:
        return replace(self, ordinal=ordinal)

    def with_section(self, section: str | None) -> ExtractedBlock:
        return replace(self, section=section)


@dataclass(frozen=True)
class EmbeddedImage:
    """A raster image found inside a document, kept for downstream OCR."""

    data: bytes
    media_type: str = "image/png"
    page: int | None = None
    ordinal: int = 0
    bbox: BBox | None = None


class ExtractionError(RuntimeError):
    """Raised when a parser cannot read a file at all."""


def normalise_text(value: str | None) -> str:
    """Collapse parser whitespace noise without destroying paragraph breaks."""
    if not value:
        return ""
    lines = [" ".join(line.split()) for line in value.replace("\r\n", "\n").split("\n")]
    kept = [line for line in lines if line]
    return "\n".join(kept).strip()


def sequence_blocks(blocks: Iterable[ExtractedBlock]) -> list[ExtractedBlock]:
    """Return a new list whose ordinals are dense and monotonic."""
    return [block.with_ordinal(index) for index, block in enumerate(blocks)]


def markdown_table(rows: Sequence[Sequence[Any]], *, has_header: bool = True) -> str:
    """Render a row matrix as a markdown table (empty string when there is none)."""
    cleaned = [[_cell(value) for value in row] for row in rows if any(_cell(v) for v in row)]
    if not cleaned:
        return ""
    width = max(len(row) for row in cleaned)
    padded = [row + [""] * (width - len(row)) for row in cleaned]
    if has_header and len(padded) > 1:
        header, body = padded[0], padded[1:]
    else:
        header, body = [f"col_{i + 1}" for i in range(width)], padded
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * width) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("|", "\\|").replace("\n", " ").strip()
    return " ".join(text.split())
