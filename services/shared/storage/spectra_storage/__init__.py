"""SPECTRA storage service.

Six logical stores plus a relational control plane behind one bundle.  Callers
import from this package only - never from a backend module - which is what lets
``.env`` decide between the embedded and the distributed profile.
"""

from __future__ import annotations

from .facade import (
    IMAGE_COLLECTION,
    LEXICAL_INDEX,
    TEXT_COLLECTION,
    Storage,
    get_storage,
    reset_storage,
)
from .factory import build_storage, describe_backends
from .interfaces import (
    CacheStore,
    GraphStore,
    LexicalDocument,
    LexicalMatch,
    LexicalStore,
    ObjectStore,
    VectorMatch,
    VectorRecord,
    VectorStore,
)
from .repository import Repository

__all__ = [
    "IMAGE_COLLECTION",
    "LEXICAL_INDEX",
    "TEXT_COLLECTION",
    "CacheStore",
    "GraphStore",
    "LexicalDocument",
    "LexicalMatch",
    "LexicalStore",
    "ObjectStore",
    "Repository",
    "Storage",
    "VectorMatch",
    "VectorRecord",
    "VectorStore",
    "build_storage",
    "describe_backends",
    "get_storage",
    "reset_storage",
]
