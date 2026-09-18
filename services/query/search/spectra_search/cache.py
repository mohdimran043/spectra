"""Query-result caching.

The key is the whole question, not just the query string.  It MUST include the
permission context, otherwise one role's results leak to another; and it MUST
include the index version plus the embedding-model identity, otherwise a reindex
or a model swap keeps serving answers computed against vectors that no longer
exist.  Both are correctness requirements, not tuning knobs.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from spectra_config.logging import get_logger
from spectra_schemas import PermissionContext, SearchRequest, SearchResponse

log = get_logger(__name__)

#: Short enough that a freshly ingested asset shows up quickly, long enough to
#: absorb an agent's repeated tool calls within one investigation.
SEARCH_CACHE_TTL_SECONDS = 300
CACHE_PREFIX = "search:v1"


def build_cache_key(
    request: SearchRequest,
    ctx: PermissionContext,
    *,
    index_version: str,
    index_signature: Any,
) -> str:
    payload = {
        "query": request.query,
        "mode": request.mode.value,
        "filters": request.filters.model_dump(mode="json"),
        "top_k": request.top_k,
        "image_asset_id": request.image_asset_id,
        "include_text": request.include_text,
        "rerank": request.rerank,
        "permissions": ctx.cache_key(),
        "index_version": index_version,
        "index_signature": index_signature,
    }
    encoded = json.dumps(payload, sort_keys=True, default=str)
    return f"{CACHE_PREFIX}:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


async def cache_get(storage: Any, key: str) -> SearchResponse | None:
    try:
        raw = await storage.cache.get(key)
    except Exception as exc:  # noqa: BLE001 - a cache outage must never fail a search
        log.warning("search.cache_get_failed", error=str(exc))
        return None
    if raw is None:
        return None
    try:
        return SearchResponse.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 - stale shape: treat as a miss
        log.warning("search.cache_decode_failed", error=str(exc))
        return None


async def cache_set(storage: Any, key: str, response: SearchResponse) -> None:
    try:
        await storage.cache.set(key, response.model_dump(mode="json"), ttl_seconds=SEARCH_CACHE_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001 - see above
        log.warning("search.cache_set_failed", error=str(exc))


async def index_identity(storage: Any, gateway: Any | None) -> tuple[str, Any]:
    """``(index_version, embedding-model signature)`` for the cache key."""
    version = "unknown"
    try:
        active = await storage.repository.active_index_version()
        if active is not None:
            version = active.key()
    except Exception as exc:  # noqa: BLE001 - versioning is advisory for the key
        log.warning("search.index_version_unavailable", error=str(exc))
    signature: Any = "no-gateway"
    if gateway is not None:
        try:
            signature = gateway.index_signature()
        except Exception as exc:  # noqa: BLE001
            log.warning("search.index_signature_unavailable", error=str(exc))
            signature = "unknown"
    return version, signature
