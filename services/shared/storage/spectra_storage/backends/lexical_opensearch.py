"""OpenSearch-backed lexical store (distributed profile).

The mapping pins payload fields to ``keyword`` through a dynamic template so the
same filter dialect the embedded backend evaluates in Python becomes exact
``term``/``terms`` clauses here - filtering must not silently become fuzzy when
the deployment scales up.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from spectra_config import Settings
from spectra_config.logging import get_logger

from ..filters import OP_EQ, FilterCondition, compile_filters
from ..interfaces import LexicalDocument, LexicalMatch, LexicalStore
from ..text_analysis import HIGHLIGHT_CLOSE, HIGHLIGHT_OPEN, MAX_HIGHLIGHTS

log = get_logger(__name__)

PAYLOAD_PREFIX = "payload"
TITLE_BOOST = 2
DEFAULT_SEARCH_LIMIT = 50
REQUEST_TIMEOUT_SECONDS = 15
HIGHLIGHT_FRAGMENT_SIZE = 180
INDEX_SETTINGS: dict[str, Any] = {
    "settings": {"index": {"number_of_shards": 1, "number_of_replicas": 0}},
    "mappings": {
        "dynamic_templates": [
            {
                "payload_strings_as_keywords": {
                    "path_match": f"{PAYLOAD_PREFIX}.*",
                    "match_mapping_type": "string",
                    "mapping": {"type": "keyword"},
                }
            }
        ],
        "properties": {
            "title": {"type": "text"},
            "text": {"type": "text"},
            PAYLOAD_PREFIX: {"type": "object", "dynamic": True},
        },
    },
}


class OpenSearchLexicalStore(LexicalStore):
    """BM25 retrieval against an OpenSearch cluster."""

    backend_name = "opensearch"

    def __init__(self, settings: Settings) -> None:
        from opensearchpy import AsyncOpenSearch  # lazy: optional dependency

        self._settings = settings
        self._client = AsyncOpenSearch(
            hosts=[settings.opensearch_url],
            timeout=REQUEST_TIMEOUT_SECONDS,
            verify_certs=False,
            ssl_show_warn=False,
        )

    # -- lifecycle --------------------------------------------------------
    async def probe(self) -> None:
        """Raise unless the cluster answers - used by the factory at start-up."""
        await self._client.info()

    async def ensure_index(self, name: str) -> None:
        if await self._client.indices.exists(index=name):
            return
        await self._client.indices.create(index=name, body=INDEX_SETTINGS)
        log.info("lexical.index_created", backend=self.backend_name, index=name)

    async def close(self) -> None:
        await self._client.close()

    # -- writes -----------------------------------------------------------
    async def index(self, index: str, documents: Sequence[LexicalDocument]) -> int:
        if not documents:
            return 0
        body: list[dict[str, Any]] = []
        for document in documents:
            body.append({"index": {"_index": index, "_id": document.id}})
            body.append(
                {
                    "title": document.title or "",
                    "text": document.text or "",
                    PAYLOAD_PREFIX: dict(document.payload or {}),
                }
            )
        await self._flush(index, body, action="index")
        return len(documents)

    async def delete(self, index: str, ids: Sequence[str]) -> int:
        if not ids:
            return 0
        body = [{"delete": {"_index": index, "_id": doc_id}} for doc_id in ids]
        await self._flush(index, body, action="delete")
        return len(ids)

    async def _flush(self, index: str, body: list[dict[str, Any]], action: str) -> None:
        response = await self._client.bulk(body=body, refresh=True)
        if not response.get("errors"):
            return
        failures = [item for item in response.get("items", []) if _failed(item)]
        log.error("lexical.bulk_failed", backend=self.backend_name, index=index, action=action, failures=len(failures))
        raise RuntimeError(f"opensearch bulk {action} failed for {len(failures)} document(s) in {index!r}")

    # -- reads ------------------------------------------------------------
    async def search(
        self,
        index: str,
        query: str,
        limit: int = DEFAULT_SEARCH_LIMIT,
        filters: dict[str, Any] | None = None,
    ) -> list[LexicalMatch]:
        if not query.strip() or limit <= 0:
            return []
        body = build_search_body(query, limit, compile_filters(filters))
        response = await self._client.search(index=index, body=body)
        hits = response.get("hits", {}).get("hits", [])
        return [_to_match(hit) for hit in hits]

    async def count(self, index: str) -> int:
        response = await self._client.count(index=index)
        return int(response.get("count", 0))

    async def health(self) -> dict[str, Any]:
        try:
            info = await self._client.info()
        except Exception as exc:  # health must never raise
            log.warning("lexical.health_failed", backend=self.backend_name, error=str(exc))
            return {"backend": self.backend_name, "status": "error", "detail": str(exc)}
        return {
            "backend": self.backend_name,
            "status": "ok",
            "url": self._settings.opensearch_url,
            "version": info.get("version", {}).get("number", "unknown"),
        }


def build_search_body(query: str, limit: int, conditions: Sequence[FilterCondition]) -> dict[str, Any]:
    """Compose the ``multi_match`` + filter + highlight request body."""
    must = {
        "multi_match": {
            "query": query,
            "fields": [f"title^{TITLE_BOOST}", "text"],
            "type": "best_fields",
            "operator": "or",
        }
    }
    return {
        "size": limit,
        "query": {"bool": {"must": [must], "filter": [_clause(c) for c in conditions]}},
        "highlight": {
            "pre_tags": [HIGHLIGHT_OPEN],
            "post_tags": [HIGHLIGHT_CLOSE],
            "fragment_size": HIGHLIGHT_FRAGMENT_SIZE,
            "number_of_fragments": MAX_HIGHLIGHTS,
            "fields": {"text": {}, "title": {}},
        },
    }


def _clause(condition: FilterCondition) -> dict[str, Any]:
    field = f"{PAYLOAD_PREFIX}.{condition.field}"
    if condition.operator == OP_EQ:
        return {"term": {field: condition.single}}
    return {"terms": {field: list(condition.values)}}


def _failed(item: dict[str, Any]) -> bool:
    return any(part.get("error") for part in item.values() if isinstance(part, dict))


def _to_match(hit: dict[str, Any]) -> LexicalMatch:
    source = hit.get("_source", {}) or {}
    fragments: list[str] = []
    for values in (hit.get("highlight", {}) or {}).values():
        fragments.extend(str(value) for value in values)
    return LexicalMatch(
        id=str(hit.get("_id", "")),
        score=round(float(hit.get("_score") or 0.0), 6),
        payload=dict(source.get(PAYLOAD_PREFIX, {}) or {}),
        highlights=fragments[:MAX_HIGHLIGHTS],
    )
