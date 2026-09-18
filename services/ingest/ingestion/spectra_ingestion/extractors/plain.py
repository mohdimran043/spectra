"""Plain-format extraction: TXT, Markdown, JSON, CSV and HTML."""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Iterator
from itertools import islice
from pathlib import Path
from typing import Any, Final

from bs4 import BeautifulSoup
from spectra_config.logging import get_logger

from .base import ExtractedBlock, ExtractionError, markdown_table, normalise_text, sequence_blocks

log = get_logger(__name__)

CSV_ROWS_PER_BLOCK: Final[int] = 25
CSV_MAX_ROWS: Final[int] = 50_000
JSON_LINES_PER_BLOCK: Final[int] = 40
JSON_MAX_LEAVES: Final[int] = 20_000
JSON_MAX_DEPTH: Final[int] = 12
HTML_BLOCK_TAGS: Final[tuple[str, ...]] = ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote", "pre")
HEADING_TAGS: Final[frozenset[str]] = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
MD_HEADING: Final[re.Pattern[str]] = re.compile(r"^(#{1,6})\s+(?P<title>.+?)\s*#*$")


def read_text(path: str | Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ExtractionError(f"cannot read {Path(path).name}: {exc}") from exc


def extract_text(path: str | Path) -> list[ExtractedBlock]:
    """Blank-line separated paragraphs of a plain text file."""
    paragraphs = [normalise_text(part) for part in re.split(r"\n\s*\n", read_text(path))]
    blocks = [ExtractedBlock(text=part, kind="paragraph") for part in paragraphs if part]
    return sequence_blocks(blocks)


def extract_markdown(path: str | Path) -> list[ExtractedBlock]:
    """Heading-aware Markdown: headings drive sections, fences become code blocks."""
    blocks: list[ExtractedBlock] = []
    section: str | None = None
    buffer: list[str] = []
    code: list[str] | None = None

    for line in read_text(path).splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            if code is None:
                buffer = _flush(buffer, blocks, section)
                code = []
            else:
                blocks.extend(_code_block(code, section))
                code = None
            continue
        if code is not None:
            code.append(line)
            continue
        heading = MD_HEADING.match(stripped)
        if heading:
            buffer = _flush(buffer, blocks, section)
            section = normalise_text(heading.group("title"))
            blocks.append(ExtractedBlock(text=section, kind="heading", section=section))
            continue
        if not stripped:
            buffer = _flush(buffer, blocks, section)
            continue
        buffer.append(line)

    _flush(buffer, blocks, section)
    if code:
        blocks.extend(_code_block(code, section))
    return sequence_blocks(blocks)


def extract_json(path: str | Path) -> list[ExtractedBlock]:
    """Flatten a JSON document into ``key.path: value`` lines grouped into blocks."""
    raw = read_text(path)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"invalid json {Path(path).name}: {exc}") from exc

    leaves = islice(_flatten(payload, "$"), JSON_MAX_LEAVES)
    lines = [f"{key}: {value}" for key, value in leaves]
    if not lines:
        return []
    blocks = [
        ExtractedBlock(
            text="\n".join(lines[start : start + JSON_LINES_PER_BLOCK]),
            kind="paragraph",
            section=_json_section(lines[start]),
            metadata={"format": "json"},
        )
        for start in range(0, len(lines), JSON_LINES_PER_BLOCK)
    ]
    return sequence_blocks(blocks)


def extract_csv(path: str | Path) -> list[ExtractedBlock]:
    """Header-aware CSV rendered as markdown tables, chunked by row groups."""
    raw = read_text(path)
    rows = _csv_rows(raw)
    if not rows:
        return []
    header, body = rows[0], rows[1:]
    if not body:
        rendered = markdown_table([header])
        return sequence_blocks([ExtractedBlock(text=rendered, kind="table")] if rendered else [])

    blocks: list[ExtractedBlock] = []
    for start in range(0, len(body), CSV_ROWS_PER_BLOCK):
        window = body[start : start + CSV_ROWS_PER_BLOCK]
        rendered = markdown_table([header, *window])
        if not rendered:
            continue
        blocks.append(
            ExtractedBlock(
                text=rendered,
                kind="table",
                metadata={"first_row": start + 2, "row_count": len(window), "columns": list(header)},
            )
        )
    return sequence_blocks(blocks)


def extract_html(path: str | Path) -> list[ExtractedBlock]:
    """BeautifulSoup extraction with script/style stripped and headings honoured."""
    soup = _soup(read_text(path))
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()

    blocks: list[ExtractedBlock] = []
    section: str | None = None
    for element in soup.find_all([*HTML_BLOCK_TAGS, "table"]):
        if element.find_parent("table") is not None:
            continue
        if element.name == "table":
            rendered = markdown_table(_html_rows(element))
            if rendered:
                blocks.append(ExtractedBlock(text=rendered, kind="table", section=section))
            continue
        text = normalise_text(element.get_text(" ", strip=True))
        if not text:
            continue
        if element.name in HEADING_TAGS:
            section = text
            blocks.append(ExtractedBlock(text=text, kind="heading", section=section))
            continue
        kind = "code" if element.name == "pre" else "paragraph"
        blocks.append(ExtractedBlock(text=text, kind=kind, section=section))
    return sequence_blocks(blocks)


def _html_rows(table: Any) -> list[list[str]]:
    return [
        [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
        for row in table.find_all("tr")
    ]


def _soup(markup: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(markup, "lxml")
    except Exception as exc:
        log.warning("html.lxml_unavailable", error=str(exc))
        return BeautifulSoup(markup, "html.parser")


def _code_block(lines: list[str], section: str | None) -> list[ExtractedBlock]:
    text = "\n".join(lines).strip()
    return [ExtractedBlock(text=text, kind="code", section=section)] if text else []


def _flush(buffer: list[str], blocks: list[ExtractedBlock], section: str | None) -> list[str]:
    text = normalise_text("\n".join(buffer))
    if text:
        kind = "table" if text.lstrip().startswith("|") else "paragraph"
        blocks.append(ExtractedBlock(text=text, kind=kind, section=section))
    return []


def _csv_rows(raw: str) -> list[list[str]]:
    dialect: Any = csv.excel
    try:
        dialect = csv.Sniffer().sniff(raw[:4096], delimiters=",;\t|")
    except csv.Error:
        log.info("csv.dialect_fallback")
    rows: list[list[str]] = []
    for index, row in enumerate(csv.reader(raw.splitlines(), dialect)):
        if index >= CSV_MAX_ROWS:
            log.warning("csv.truncated", limit=CSV_MAX_ROWS)
            break
        if any(str(cell).strip() for cell in row):
            rows.append([str(cell) for cell in row])
    return rows


def _flatten(payload: Any, prefix: str, depth: int = 0) -> Iterator[tuple[str, str]]:
    if depth > JSON_MAX_DEPTH:
        yield prefix, "<max depth>"
        return
    if isinstance(payload, dict):
        for key, value in payload.items():
            yield from _flatten(value, f"{prefix}.{key}", depth + 1)
        return
    if isinstance(payload, list):
        for index, value in enumerate(payload):
            yield from _flatten(value, f"{prefix}[{index}]", depth + 1)
        return
    yield prefix, "" if payload is None else str(payload)


def _json_section(first_line: str) -> str | None:
    path = first_line.split(":", 1)[0]
    parts = path.split(".")
    return parts[1].split("[")[0] if len(parts) > 1 else None
