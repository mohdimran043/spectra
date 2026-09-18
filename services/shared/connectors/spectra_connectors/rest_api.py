"""REST / JSON API connector.

``connection`` example::

    {"base_url": "https://api.example.com", "resource": "/v1/tickets",
     "record_path": "data.items", "id_field": "id", "name_field": "subject",
     "updated_field": "updated_at",
     "auth": {"type": "bearer"},
     "pagination": {"strategy": "cursor", "cursor_param": "cursor",
                    "cursor_path": "meta.next_cursor", "page_size": 100},
     "allow_private_network": false}

Credentials come from ``credential_ref`` only.  Every request target - including
each redirect hop - is checked by :mod:`spectra_connectors.net_guard`, so a
source cannot be pointed at ``169.254.169.254`` or any other internal address
unless ``allow_private_network`` is explicitly set.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Any, ClassVar

import httpx
from spectra_config.logging import get_logger
from spectra_schemas.catalog import SourceDescriptor, SourceHealth
from spectra_schemas.enums import AssetKind, SourceStatus, SourceType

from .base import DiscoveredItem, SourceConnector
from .credentials import CredentialStore, redact
from .errors import ConfigurationError, ConnectionFailed
from .net_guard import assert_safe_url

log = get_logger(__name__)

DEFAULT_PAGE_SIZE = 100
DEFAULT_MAX_PAGES = 10_000
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_SECONDS = 0.5
MAX_BACKOFF_SECONDS = 30.0
MAX_REDIRECTS = 3
RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

STRATEGY_NONE = "none"
STRATEGY_OFFSET = "offset"
STRATEGY_PAGE = "page"
STRATEGY_CURSOR = "cursor"
STRATEGY_LINK = "link"
STRATEGIES = frozenset({STRATEGY_NONE, STRATEGY_OFFSET, STRATEGY_PAGE, STRATEGY_CURSOR, STRATEGY_LINK})


@dataclass(frozen=True, slots=True)
class PageRequest:
    """One page to fetch: an absolute URL plus its query parameters."""

    url: str
    params: Mapping[str, Any]


class RestApiConnector(SourceConnector):
    """Streams JSON records from a paginated HTTP API."""

    source_type: ClassVar[SourceType] = SourceType.REST_API

    def __init__(
        self,
        descriptor: SourceDescriptor,
        credentials: CredentialStore | None = None,
    ) -> None:
        super().__init__(descriptor, credentials)
        base_url = str(self.config("base_url") or "").rstrip("/")
        if not base_url:
            raise ConfigurationError("rest_api source requires connection['base_url']")
        self._base_url = base_url
        self._resource = str(self.config("resource") or "")
        self._method = str(self.config("method") or "GET").upper()
        self._record_path = str(self.config("record_path") or "")
        self._id_field = str(self.config("id_field") or "id")
        self._name_field = str(self.config("name_field") or self._id_field)
        self._updated_field = self.config("updated_field")
        self._allow_private = bool(self.config("allow_private_network", False))
        self._verify_tls = bool(self.config("verify_tls", True))
        self._timeout = float(self.config("timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
        self._max_retries = int(self.config("max_retries", DEFAULT_MAX_RETRIES))
        self._pagination = dict(self.config("pagination") or {})
        self._strategy = str(self._pagination.get("strategy") or STRATEGY_NONE).lower()
        if self._strategy not in STRATEGIES:
            raise ConfigurationError(
                f"unknown pagination strategy {self._strategy!r}: expected one of {sorted(STRATEGIES)}"
            )
        self._page_size = int(self._pagination.get("page_size") or DEFAULT_PAGE_SIZE)
        self._max_pages = int(self._pagination.get("max_pages") or DEFAULT_MAX_PAGES)
        self._client: httpx.AsyncClient | None = None

    @property
    def endpoint(self) -> str:
        return f"{self._base_url}{self._resource}"

    # -- lifecycle --------------------------------------------------------
    async def connect(self) -> None:
        if self._client is not None:
            return
        await asyncio.to_thread(partial(assert_safe_url, self.endpoint, allow_private=self._allow_private))
        self._client = httpx.AsyncClient(
            headers=self._headers(),
            timeout=self._timeout,
            verify=self._verify_tls,
            follow_redirects=False,
        )
        self._connected = True
        log.info(
            "rest_api.connected",
            source_id=self.source_id,
            endpoint=self.endpoint,
            auth=self._auth_type,
            connection=self.safe_connection(),
        )

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()
        await super().close()

    @property
    def _auth_type(self) -> str:
        return str(dict(self.config("auth") or {}).get("type") or "none").lower()

    def _headers(self) -> dict[str, str]:
        headers = {
            "accept": "application/json",
            "user-agent": "spectra-connector/1.0",
            **{str(key): str(value) for key, value in dict(self.config("headers") or {}).items()},
        }
        return {**headers, **self._auth_headers()}

    def _auth_headers(self) -> dict[str, str]:
        auth = dict(self.config("auth") or {})
        kind = self._auth_type
        if kind in ("", "none"):
            return {}
        secret = self._credentials.resolve(self._descriptor.credential_ref)
        token = secret.get("token") or secret.get("value") or secret.get("api_key")
        if kind == "bearer":
            return {"authorization": f"Bearer {_require(token, 'token')}"}
        if kind == "header":
            header = str(auth.get("header") or "x-api-key")
            return {header.lower(): str(_require(token, 'token'))}
        if kind == "basic":
            username = str(secret.get("username") or auth.get("username") or "")
            password = str(secret.get("password") or token or "")
            encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
            return {"authorization": f"Basic {encoded}"}
        raise ConfigurationError(f"unsupported auth type {kind!r}")

    # -- discovery --------------------------------------------------------
    async def validate(self) -> SourceHealth:
        started = time.perf_counter()
        try:
            await self.connect()
            response = await self._request(PageRequest(self.endpoint, self._first_params()))
            records = _records(response.json(), self._record_path)
        except Exception as exc:  # noqa: BLE001 - health must never raise
            log.warning("rest_api.validate_failed", source_id=self.source_id, error=str(exc))
            return self._health(SourceStatus.UNREACHABLE, detail=str(exc), started=started)
        return self._health(
            SourceStatus.HEALTHY,
            detail=f"{len(records)} record(s) on the first page",
            started=started,
            record_count=len(records),
        )

    async def discover(self) -> AsyncIterator[DiscoveredItem]:
        """Stream every record, one page at a time - pages are never accumulated."""
        await self.connect()
        request: PageRequest | None = PageRequest(self.endpoint, self._first_params())
        pages = 0
        while request is not None and pages < self._max_pages:
            response = await self._request(request)
            payload = response.json()
            records = _records(payload, self._record_path)
            for record in records:
                yield self._item(record)
            self._record_checkpoint(_cursor_of(request), added=len(records))
            pages += 1
            request = self._next_page(request, response, payload, len(records))

    def _first_params(self) -> dict[str, Any]:
        params = {str(k): v for k, v in dict(self.config("params") or {}).items()}
        resumed = _params_from_cursor(self._checkpoint.cursor)
        if self._strategy == STRATEGY_OFFSET:
            params.setdefault(str(self._pagination.get("limit_param") or "limit"), self._page_size)
            params.setdefault(str(self._pagination.get("offset_param") or "offset"), 0)
        elif self._strategy == STRATEGY_PAGE:
            params.setdefault(str(self._pagination.get("limit_param") or "per_page"), self._page_size)
            params.setdefault(
                str(self._pagination.get("page_param") or "page"),
                int(self._pagination.get("start_page") or 1),
            )
        elif self._strategy == STRATEGY_CURSOR:
            params.setdefault(str(self._pagination.get("limit_param") or "limit"), self._page_size)
        return {**params, **resumed}

    def _next_page(
        self,
        request: PageRequest,
        response: httpx.Response,
        payload: Any,
        received: int,
    ) -> PageRequest | None:
        if received == 0 and self._strategy != STRATEGY_LINK:
            return None
        if self._strategy == STRATEGY_OFFSET:
            key = str(self._pagination.get("offset_param") or "offset")
            offset = int(request.params.get(key, 0)) + max(received, self._page_size)
            return PageRequest(request.url, {**request.params, key: offset})
        if self._strategy == STRATEGY_PAGE:
            key = str(self._pagination.get("page_param") or "page")
            return PageRequest(request.url, {**request.params, key: int(request.params.get(key, 1)) + 1})
        if self._strategy == STRATEGY_CURSOR:
            cursor = _dig(payload, str(self._pagination.get("cursor_path") or "next_cursor"))
            if not cursor:
                return None
            key = str(self._pagination.get("cursor_param") or "cursor")
            return PageRequest(request.url, {**request.params, key: cursor})
        if self._strategy == STRATEGY_LINK:
            next_url = response.links.get("next", {}).get("url")
            return None if not next_url else PageRequest(str(next_url), {})
        return None

    def _item(self, record: Mapping[str, Any]) -> DiscoveredItem:
        external_id = str(record.get(self._id_field, "")) or _hashed(record)
        name = str(record.get(self._name_field, external_id))
        return DiscoveredItem(
            external_id=external_id,
            name=name,
            media_type="application/json",
            size=len(json.dumps(record, default=str).encode("utf-8")),
            modified_at=_timestamp(record.get(self._updated_field) if self._updated_field else None),
            kind=AssetKind.DOCUMENT,
            extra={"record": dict(record), "resource": self._resource or self._base_url},
        )

    async def fetch(self, item: DiscoveredItem) -> bytes:
        """Return the record as JSON bytes, re-fetching it only if necessary."""
        record = item.extra.get("record")
        if record is None:
            response = await self._request(PageRequest(f"{self.endpoint}/{item.external_id}", {}))
            record = response.json()
        return json.dumps(record, default=str).encode("utf-8")

    async def metadata(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "type": self.source_type.value,
            "endpoint": self.endpoint,
            "method": self._method,
            "auth": self._auth_type,
            "pagination": redact(self._pagination),
            "record_path": self._record_path,
            "allow_private_network": self._allow_private,
            "connection": self.safe_connection(),
        }

    # -- transport --------------------------------------------------------
    async def _request(self, request: PageRequest) -> httpx.Response:
        await self.connect()
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                return await self._send(request)
            except (httpx.HTTPError, ConnectionFailed) as exc:
                last_error = exc
                if attempt >= self._max_retries:
                    break
                delay = min(DEFAULT_BACKOFF_SECONDS * (2**attempt), MAX_BACKOFF_SECONDS)
                log.warning(
                    "rest_api.retry",
                    source_id=self.source_id,
                    url=request.url,
                    attempt=attempt + 1,
                    delay_seconds=delay,
                    error=str(exc),
                )
                await asyncio.sleep(delay)
        raise ConnectionFailed(f"request to {request.url} failed: {last_error}") from last_error

    async def _send(self, request: PageRequest) -> httpx.Response:
        client = self._client
        if client is None:  # pragma: no cover - connect() raises first
            raise ConnectionFailed(f"source {self.source_id} is not connected")
        url, params = request.url, dict(request.params)
        for _hop in range(MAX_REDIRECTS + 1):
            await asyncio.to_thread(partial(assert_safe_url, url, allow_private=self._allow_private))
            response = await client.request(self._method, url, params=params or None)
            if response.is_redirect and response.headers.get("location"):
                url = str(response.next_request.url) if response.next_request else ""
                params = {}
                continue
            if response.status_code in RETRY_STATUS:
                raise ConnectionFailed(f"{response.status_code} from {url}")
            response.raise_for_status()
            return response
        raise ConnectionFailed(f"too many redirects from {request.url}")


# -- payload helpers ------------------------------------------------------
def _require(value: Any, field: str) -> str:
    if not value:
        raise ConfigurationError(f"credential for this source is missing {field!r}")
    return str(value)


def _dig(payload: Any, path: str) -> Any:
    """Walk a dotted path (``data.items``) - the JSONPath subset we need."""
    current = payload
    for segment in (part for part in path.split(".") if part):
        if isinstance(current, Mapping):
            current = current.get(segment)
        elif isinstance(current, list) and segment.isdigit():
            index = int(segment)
            current = current[index] if index < len(current) else None
        else:
            return None
    return current


def _records(payload: Any, record_path: str) -> tuple[Mapping[str, Any], ...]:
    extracted = _dig(payload, record_path) if record_path else payload
    if isinstance(extracted, Mapping):
        return (extracted,)
    if isinstance(extracted, list):
        return tuple(item for item in extracted if isinstance(item, Mapping))
    return ()


def _cursor_of(request: PageRequest) -> str:
    return json.dumps({"url": request.url, "params": dict(request.params)}, sort_keys=True, default=str)


def _params_from_cursor(cursor: str | None) -> dict[str, Any]:
    if not cursor:
        return {}
    try:
        payload = json.loads(cursor)
    except json.JSONDecodeError:
        log.warning("rest_api.bad_checkpoint", cursor=cursor[:120])
        return {}
    params = payload.get("params") if isinstance(payload, Mapping) else None
    return dict(params) if isinstance(params, Mapping) else {}


def _timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _hashed(record: Mapping[str, Any]) -> str:
    payload = json.dumps(record, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:32]
