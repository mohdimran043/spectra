"""Format-independent description of a generated document.

Content generation states *what* a document says; the writers decide how that
becomes a PDF page, a Word paragraph, a slide or a spreadsheet row.  Keeping
the two apart is what lets the same incident narrative exist as a 16-page PDF
and as a one-page memo without duplicating the prose.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

#: Supported output formats, each owned by exactly one writer.
FORMAT_PDF: Final[str] = "pdf"
FORMAT_DOCX: Final[str] = "docx"
FORMAT_PPTX: Final[str] = "pptx"
FORMAT_XLSX: Final[str] = "xlsx"
FORMAT_CSV: Final[str] = "csv"
FORMAT_MD: Final[str] = "md"
FORMAT_HTML: Final[str] = "html"
FORMAT_TXT: Final[str] = "txt"

MEDIA_TYPES: Final[dict[str, str]] = {
    FORMAT_PDF: "application/pdf",
    FORMAT_DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    FORMAT_PPTX: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    FORMAT_XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    FORMAT_CSV: "text/csv",
    FORMAT_MD: "text/markdown",
    FORMAT_HTML: "text/html",
    FORMAT_TXT: "text/plain",
}

VERSION_CURRENT: Final[str] = "current"
VERSION_SUPERSEDED: Final[str] = "superseded"
VERSION_DRAFT: Final[str] = "draft"


@dataclass(frozen=True)
class Section:
    """One heading plus its paragraphs.  In a PDF, one section is one page."""

    heading: str
    paragraphs: tuple[str, ...]


@dataclass(frozen=True)
class DocumentSpec:
    """Everything needed to write one document and to describe it in the manifest."""

    slug: str
    fmt: str
    title: str
    sections: tuple[Section, ...] = ()
    version: str = "1"
    version_status: str = VERSION_CURRENT
    key_section: int | None = None
    key_finding: str | None = None
    tags: tuple[str, ...] = ()
    occurred_at: datetime | None = None
    headers: tuple[str, ...] = ()
    rows: tuple[tuple[str, ...], ...] = ()
    entities: tuple[str, ...] = field(default_factory=tuple)
    author: str = "SPECTRA demo generator"

    @property
    def media_type(self) -> str:
        return MEDIA_TYPES[self.fmt]

    @property
    def filename(self) -> str:
        return f"{self.slug}.{self.fmt}"

    @property
    def key_page(self) -> int | None:
        """1-based page carrying the key finding - PDFs put one section per page."""
        if self.key_section is None:
            return None
        return self.key_section + 1


def section(heading: str, *paragraphs: str) -> Section:
    return Section(heading=heading, paragraphs=tuple(paragraph for paragraph in paragraphs if paragraph))
