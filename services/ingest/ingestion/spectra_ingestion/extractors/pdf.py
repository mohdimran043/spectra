"""PDF extraction with PyMuPDF: text + bbox, headings, tables and inline images."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from statistics import median
from typing import Any, Final

import pymupdf
from spectra_config.logging import get_logger

from .base import (
    BBox,
    EmbeddedImage,
    ExtractedBlock,
    ExtractionError,
    markdown_table,
    normalise_text,
    sequence_blocks,
)

log = get_logger(__name__)

#: A line counts as a heading when it is this much larger than the body font.
HEADING_SIZE_RATIO: Final[float] = 1.18
HEADING_MAX_CHARS: Final[int] = 120
FONT_SAMPLE_PAGES: Final[int] = 20
MIN_IMAGE_BYTES: Final[int] = 2048
MIN_IMAGE_EDGE: Final[int] = 64
MAX_EMBEDDED_IMAGES: Final[int] = 40
BOLD_FLAG: Final[int] = 1 << 4


def extract(path: str | Path) -> list[ExtractedBlock]:
    """Return every text / heading / table block of a PDF, in reading order."""
    target = Path(path)
    try:
        document = pymupdf.open(target)
    except Exception as exc:
        raise ExtractionError(f"cannot open pdf {target.name}: {exc}") from exc

    blocks: list[ExtractedBlock] = []
    try:
        body_size = _body_font_size(document)
        section: str | None = None
        for page_index in range(document.page_count):
            page_blocks, section = _extract_page(document, page_index, body_size, section)
            blocks.extend(page_blocks)
    finally:
        document.close()
    return sequence_blocks(blocks)


def extract_images(path: str | Path, *, limit: int = MAX_EMBEDDED_IMAGES) -> list[EmbeddedImage]:
    """Return embedded raster images large enough to be worth OCR-ing."""
    target = Path(path)
    try:
        document = pymupdf.open(target)
    except Exception as exc:
        raise ExtractionError(f"cannot open pdf {target.name}: {exc}") from exc

    images: list[EmbeddedImage] = []
    try:
        for page_index in range(document.page_count):
            if len(images) >= limit:
                break
            images.extend(_page_images(document, page_index, limit - len(images)))
    finally:
        document.close()
    return [replace(image, ordinal=index) for index, image in enumerate(images)]


def page_count(path: str | Path) -> int:
    try:
        with pymupdf.open(Path(path)) as document:
            return int(document.page_count)
    except Exception as exc:
        raise ExtractionError(f"cannot read page count: {exc}") from exc


def _extract_page(
    document: pymupdf.Document, page_index: int, body_size: float, section: str | None
) -> tuple[list[ExtractedBlock], str | None]:
    page_no = page_index + 1
    try:
        page = document.load_page(page_index)
        raw = page.get_text("dict")
    except Exception as exc:
        log.warning("pdf.page_failed", page=page_no, error=str(exc))
        return [], section

    tables = _find_tables(page, page_no)
    table_boxes = [bbox for _, bbox, _ in tables if bbox is not None]
    blocks: list[ExtractedBlock] = []
    for raw_block in raw.get("blocks", []):
        if raw_block.get("type") != 0:
            continue
        bbox = _as_bbox(raw_block.get("bbox"))
        if _inside_any(bbox, table_boxes):
            continue
        text, max_size, bold = _block_text(raw_block)
        if not text:
            continue
        if _is_heading(text, max_size, body_size, bold=bold):
            section = text
            blocks.append(ExtractedBlock(text=text, kind="heading", page=page_no, section=section, bbox=bbox))
            continue
        blocks.append(ExtractedBlock(text=text, kind="paragraph", page=page_no, section=section, bbox=bbox))

    table_blocks = [
        ExtractedBlock(
            text=rendered,
            kind="table",
            page=page_no,
            section=section,
            bbox=bbox,
            metadata={"table_index": index},
        )
        for rendered, bbox, index in tables
    ]
    return blocks + table_blocks, section


def _find_tables(page: pymupdf.Page, page_no: int) -> list[tuple[str, BBox | None, int]]:
    """Rendered tables plus their bounding boxes, so text inside them is skipped."""
    finder = getattr(page, "find_tables", None)
    if finder is None:
        return []
    try:
        found = list(finder().tables)
    except Exception as exc:
        log.warning("pdf.tables_failed", page=page_no, error=str(exc))
        return []

    tables: list[tuple[str, BBox | None, int]] = []
    for index, table in enumerate(found):
        try:
            rendered = markdown_table(table.extract())
        except Exception as exc:
            log.warning("pdf.table_extract_failed", page=page_no, error=str(exc))
            continue
        if rendered:
            tables.append((rendered, _as_bbox(getattr(table, "bbox", None)), index))
    return tables


def _page_images(document: pymupdf.Document, page_index: int, remaining: int) -> list[EmbeddedImage]:
    page_no = page_index + 1
    try:
        page = document.load_page(page_index)
        refs = page.get_images(full=True)
    except Exception as exc:
        log.warning("pdf.images_failed", page=page_no, error=str(exc))
        return []

    images: list[EmbeddedImage] = []
    for ref in refs:
        if len(images) >= remaining:
            break
        image = _extract_image(document, page, int(ref[0]), page_no)
        if image is not None:
            images.append(image)
    return images


def _extract_image(
    document: pymupdf.Document, page: pymupdf.Page, xref: int, page_no: int
) -> EmbeddedImage | None:
    try:
        payload = document.extract_image(xref)
    except Exception as exc:
        log.warning("pdf.image_extract_failed", page=page_no, xref=xref, error=str(exc))
        return None
    data = payload.get("image") or b""
    if len(data) < MIN_IMAGE_BYTES:
        return None
    if min(int(payload.get("width", 0)), int(payload.get("height", 0))) < MIN_IMAGE_EDGE:
        return None
    return EmbeddedImage(
        data=data,
        media_type=f"image/{payload.get('ext', 'png')}",
        page=page_no,
        bbox=_image_bbox(page, xref),
    )


def _image_bbox(page: pymupdf.Page, xref: int) -> BBox | None:
    try:
        rects = page.get_image_rects(xref)
    except Exception:
        return None
    return _as_bbox(tuple(rects[0])) if rects else None


def _body_font_size(document: pymupdf.Document) -> float:
    sizes: list[float] = []
    for page_index in range(min(document.page_count, FONT_SAMPLE_PAGES)):
        try:
            raw = document.load_page(page_index).get_text("dict")
        except Exception:
            continue
        for block in raw.get("blocks", []):
            for line in block.get("lines", []):
                sizes.extend(float(span.get("size", 0.0)) for span in line.get("spans", []))
    positive = [size for size in sizes if size > 0]
    return median(positive) if positive else 10.0


def _block_text(raw_block: dict[str, Any]) -> tuple[str, float, bool]:
    parts: list[str] = []
    max_size = 0.0
    bold = False
    for line in raw_block.get("lines", []):
        spans = line.get("spans", [])
        parts.append("".join(str(span.get("text", "")) for span in spans))
        for span in spans:
            max_size = max(max_size, float(span.get("size", 0.0)))
            bold = bold or bool(int(span.get("flags", 0)) & BOLD_FLAG)
    return normalise_text("\n".join(parts)), max_size, bold


def _is_heading(text: str, size: float, body_size: float, *, bold: bool) -> bool:
    if len(text) > HEADING_MAX_CHARS or "\n" in text:
        return False
    if text.endswith((".", ",", ";")):
        return False
    if size >= body_size * HEADING_SIZE_RATIO:
        return True
    return bold and size >= body_size and len(text) < HEADING_MAX_CHARS // 2


def _as_bbox(value: Any) -> BBox | None:
    if value is None:
        return None
    try:
        x0, y0, x1, y1 = (round(float(part), 2) for part in tuple(value)[:4])
    except (TypeError, ValueError):
        return None
    return (x0, y0, x1, y1)


def _inside_any(bbox: BBox | None, boxes: list[BBox]) -> bool:
    if bbox is None or not boxes:
        return False
    return any(
        bbox[0] >= box[0] - 1 and bbox[1] >= box[1] - 1 and bbox[2] <= box[2] + 1 and bbox[3] <= box[3] + 1
        for box in boxes
    )
