"""Concrete storage backends.

Only the embedded backends are imported eagerly.  The distributed ones
(Qdrant, OpenSearch, Neo4j, S3, Redis) are imported by ``factory`` on demand so
``import spectra_storage`` works on a machine that has none of them installed.
"""

from __future__ import annotations

from .cache_memory import MemoryCacheStore
from .graph_embedded import EmbeddedGraphStore
from .lexical_embedded import EmbeddedLexicalStore
from .object_filesystem import FilesystemObjectStore
from .vector_embedded import EmbeddedVectorStore

__all__ = [
    "EmbeddedGraphStore",
    "EmbeddedLexicalStore",
    "EmbeddedVectorStore",
    "FilesystemObjectStore",
    "MemoryCacheStore",
]
