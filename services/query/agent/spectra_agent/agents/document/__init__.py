"""Document Agent - the written record.

Searches every ingested document (PDF, Office, email, plain text) with hybrid
lexical + semantic retrieval, and opens a named page when a claim has to be read
at the exact locator it came from.  It is the first stop of the retrieval
pipeline and supplies most of the evidence an answer is finally built on.

Switched off with the ``document`` deployment flag.
"""

from __future__ import annotations

from .tools import DOCUMENT_TOOLS, GetDocumentPageTool, SearchDocumentsTool

__all__ = ["DOCUMENT_TOOLS", "GetDocumentPageTool", "SearchDocumentsTool"]
