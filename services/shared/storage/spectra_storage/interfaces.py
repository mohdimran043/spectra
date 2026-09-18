"""Storage protocols.

SPECTRA talks to six logical stores.  Each has an *embedded* backend (SQLite /
filesystem / in-process, zero infrastructure) and a *distributed* backend
(Qdrant / OpenSearch / Neo4j / S3 / Redis / PostgreSQL).  Nothing above this
layer knows which is active, which is what lets the same agent code run on a
laptop and on a cluster - see docs/scaling.md.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VectorRecord:
    """One embedded point plus the payload needed for filtering."""

    id: str
    vector: Sequence[float]
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VectorMatch:
    id: str
    score: float
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LexicalDocument:
    id: str
    text: str
    title: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LexicalMatch:
    id: str
    score: float
    payload: dict[str, Any] = field(default_factory=dict)
    highlights: list[str] = field(default_factory=list)


class VectorStore(ABC):
    """Dense/multimodal ANN retrieval."""

    backend_name: str = "abstract"

    @abstractmethod
    async def ensure_collection(self, name: str, dimension: int) -> None: ...

    @abstractmethod
    async def upsert(self, collection: str, records: Sequence[VectorRecord]) -> int: ...

    @abstractmethod
    async def search(
        self,
        collection: str,
        vector: Sequence[float],
        limit: int = 50,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorMatch]: ...

    @abstractmethod
    async def delete(self, collection: str, ids: Sequence[str]) -> int: ...

    @abstractmethod
    async def count(self, collection: str) -> int: ...

    async def health(self) -> dict[str, Any]:
        return {"backend": self.backend_name, "status": "ok"}

    async def close(self) -> None:  # pragma: no cover - trivial
        return None


class LexicalStore(ABC):
    """BM25 / full-text retrieval and large-scale metadata search."""

    backend_name: str = "abstract"

    @abstractmethod
    async def ensure_index(self, name: str) -> None: ...

    @abstractmethod
    async def index(self, index: str, documents: Sequence[LexicalDocument]) -> int: ...

    @abstractmethod
    async def search(
        self,
        index: str,
        query: str,
        limit: int = 50,
        filters: dict[str, Any] | None = None,
    ) -> list[LexicalMatch]: ...

    @abstractmethod
    async def delete(self, index: str, ids: Sequence[str]) -> int: ...

    @abstractmethod
    async def count(self, index: str) -> int: ...

    async def health(self) -> dict[str, Any]:
        return {"backend": self.backend_name, "status": "ok"}

    async def close(self) -> None:  # pragma: no cover - trivial
        return None


class GraphStore(ABC):
    """Entity / evidence / investigation graph."""

    backend_name: str = "abstract"

    @abstractmethod
    async def upsert_node(self, node_id: str, labels: Sequence[str], properties: dict[str, Any]) -> None: ...

    @abstractmethod
    async def upsert_edge(
        self,
        edge_type: str,
        start: str,
        end: str,
        properties: dict[str, Any] | None = None,
    ) -> str: ...

    @abstractmethod
    async def neighbours(
        self,
        node_id: str,
        depth: int = 1,
        edge_types: Sequence[str] | None = None,
        limit: int = 100,
    ) -> dict[str, Any]: ...

    @abstractmethod
    async def get_node(self, node_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    async def find_nodes(
        self, label: str, properties: dict[str, Any] | None = None, limit: int = 50
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def paths(self, start: str, end: str, max_depth: int = 4) -> list[list[dict[str, Any]]]: ...

    @abstractmethod
    async def counts(self) -> dict[str, int]: ...

    async def health(self) -> dict[str, Any]:
        return {"backend": self.backend_name, "status": "ok"}

    async def close(self) -> None:  # pragma: no cover - trivial
        return None


class ObjectStore(ABC):
    """Content-addressed blob storage.  Keys are ``spectra://`` URIs, never paths."""

    backend_name: str = "abstract"

    @abstractmethod
    async def put(self, uri: str, data: bytes, media_type: str = "application/octet-stream") -> str: ...

    @abstractmethod
    async def get(self, uri: str) -> bytes: ...

    @abstractmethod
    async def exists(self, uri: str) -> bool: ...

    @abstractmethod
    async def delete(self, uri: str) -> bool: ...

    @abstractmethod
    async def local_path(self, uri: str) -> str:
        """Materialise locally for tools that need a real file (ffmpeg, OCR)."""

    async def health(self) -> dict[str, Any]:
        return {"backend": self.backend_name, "status": "ok"}

    async def close(self) -> None:  # pragma: no cover - trivial
        return None


class CacheStore(ABC):
    """Short-lived agent state, query caches, job state."""

    backend_name: str = "abstract"

    @abstractmethod
    async def get(self, key: str) -> Any | None: ...

    @abstractmethod
    async def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def incr(self, key: str, amount: int = 1) -> int: ...

    async def health(self) -> dict[str, Any]:
        return {"backend": self.backend_name, "status": "ok"}

    async def close(self) -> None:  # pragma: no cover - trivial
        return None
