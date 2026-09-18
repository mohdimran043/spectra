"""S3-compatible object storage connector (AWS S3 and MinIO).

``endpoint_url`` is what makes one class serve both: leave it unset for AWS, set
it to ``http://minio:9000`` for MinIO or any other S3-compatible store.

``connection`` example::

    {"bucket": "evidence", "prefix": "cases/2024/",
     "endpoint_url": "http://localhost:9000", "region": "us-east-1",
     "addressing_style": "path"}

Keys are resolved from ``credential_ref``; when none is set, boto3's default
chain (instance role, ``~/.aws``, environment) applies, which is the right
behaviour for an EC2/EKS deployment with an instance profile.

boto3 is imported lazily inside :meth:`_build_client`, so importing this module
costs nothing when the source type is unused.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Mapping
from typing import Any, ClassVar

from spectra_config import Settings, get_settings
from spectra_config.logging import get_logger
from spectra_schemas.catalog import SourceDescriptor, SourceHealth
from spectra_schemas.enums import SourceStatus, SourceType

from .base import DiscoveredItem, SourceConnector
from .credentials import CredentialStore
from .errors import ConfigurationError, ConnectionFailed, DriverUnavailable
from .media import classify

log = get_logger(__name__)

DEFAULT_PAGE_SIZE = 1000
DEFAULT_REGION = "us-east-1"
DEFAULT_CONNECT_TIMEOUT = 10
DEFAULT_READ_TIMEOUT = 60
DEFAULT_MAX_ATTEMPTS = 3


class S3Connector(SourceConnector):
    """Streams objects from an S3-compatible bucket."""

    source_type: ClassVar[SourceType] = SourceType.S3

    def __init__(
        self,
        descriptor: SourceDescriptor,
        credentials: CredentialStore | None = None,
        *,
        settings: Settings | None = None,
    ) -> None:
        super().__init__(descriptor, credentials)
        self._settings = settings or get_settings()
        bucket = self.config("bucket")
        if not bucket:
            raise ConfigurationError("s3 source requires connection['bucket']")
        self._bucket = str(bucket)
        self._prefix = str(self.config("prefix") or "")
        self._page_size = int(self.config("page_size", DEFAULT_PAGE_SIZE))
        self._max_bytes = int(self.config("max_bytes", self._settings.max_upload_bytes))
        self._client: Any | None = None
        self._lock = asyncio.Lock()

    @property
    def bucket(self) -> str:
        return self._bucket

    # -- lifecycle --------------------------------------------------------
    async def connect(self) -> None:
        if self._client is not None:
            return
        async with self._lock:
            if self._client is None:
                self._client = await asyncio.to_thread(self._build_client)
                self._connected = True
                log.info(
                    "s3.connected",
                    source_id=self.source_id,
                    bucket=self._bucket,
                    endpoint=self.config("endpoint_url") or "aws",
                    connection=self.safe_connection(),
                )

    def _build_client(self) -> Any:
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:
            raise DriverUnavailable("the s3 connector needs boto3: pip install boto3") from exc
        secret = self._credentials.resolve(self._descriptor.credential_ref)
        config = Config(
            region_name=str(self.config("region") or DEFAULT_REGION),
            s3={"addressing_style": str(self.config("addressing_style") or "auto")},
            connect_timeout=int(self.config("connect_timeout", DEFAULT_CONNECT_TIMEOUT)),
            read_timeout=int(self.config("read_timeout", DEFAULT_READ_TIMEOUT)),
            retries={"max_attempts": int(self.config("max_attempts", DEFAULT_MAX_ATTEMPTS))},
        )
        return boto3.client(
            "s3",
            endpoint_url=self.config("endpoint_url") or None,
            aws_access_key_id=secret.get("access_key_id") or secret.get("username"),
            aws_secret_access_key=secret.get("secret_access_key") or secret.get("value"),
            aws_session_token=secret.get("session_token"),
            use_ssl=bool(self.config("use_ssl", True)),
            verify=bool(self.config("verify_tls", True)),
            config=config,
        )

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await asyncio.to_thread(client.close)
        await super().close()

    async def _require_client(self) -> Any:
        await self.connect()
        if self._client is None:  # pragma: no cover - connect() raises first
            raise ConnectionFailed(f"source {self.source_id} is not connected")
        return self._client

    # -- discovery --------------------------------------------------------
    async def validate(self) -> SourceHealth:
        started = time.perf_counter()
        try:
            client = await self._require_client()
            await asyncio.to_thread(client.head_bucket, Bucket=self._bucket)
        except Exception as exc:  # noqa: BLE001 - health must never raise
            log.warning("s3.validate_failed", source_id=self.source_id, error=str(exc))
            return self._health(SourceStatus.UNREACHABLE, detail=_reason(exc), started=started)
        return self._health(
            SourceStatus.HEALTHY,
            detail=f"bucket {self._bucket!r} reachable",
            started=started,
        )

    async def discover(self) -> AsyncIterator[DiscoveredItem]:
        """Stream objects page by page.

        ``list_objects_v2`` is called directly (rather than through a paginator)
        so the continuation token is visible and can be checkpointed: an
        interrupted sync of a million-object bucket resumes at the next page
        instead of restarting.
        """
        client = await self._require_client()
        token, start_after = _resume(self._checkpoint.cursor)
        while True:
            page = await asyncio.to_thread(self._list_page, client, token, start_after)
            contents = page.get("Contents") or []
            for entry in contents:
                item = self._item(entry)
                self._record_checkpoint(_cursor(page.get("NextContinuationToken"), item.external_id), added=1)
                yield item
            token = page.get("NextContinuationToken")
            start_after = None
            if not page.get("IsTruncated") or not token:
                return

    def _list_page(self, client: Any, token: str | None, start_after: str | None) -> Mapping[str, Any]:
        request: dict[str, Any] = {
            "Bucket": self._bucket,
            "MaxKeys": self._page_size,
        }
        if self._prefix:
            request["Prefix"] = self._prefix
        if token:
            request["ContinuationToken"] = token
        elif start_after:
            request["StartAfter"] = start_after
        try:
            return client.list_objects_v2(**request)
        except Exception as exc:  # noqa: BLE001 - botocore errors are dynamic
            raise ConnectionFailed(f"cannot list s3://{self._bucket}/{self._prefix}: {_reason(exc)}") from exc

    def _item(self, entry: Mapping[str, Any]) -> DiscoveredItem:
        key = str(entry.get("Key"))
        media_type, kind = classify(key)
        return DiscoveredItem(
            external_id=key,
            name=key.rsplit("/", 1)[-1] or key,
            media_type=media_type,
            size=int(entry.get("Size") or 0),
            modified_at=entry.get("LastModified"),
            kind=kind,
            extra={
                "bucket": self._bucket,
                "key": key,
                "etag": str(entry.get("ETag") or "").strip('"'),
                "storage_class": entry.get("StorageClass"),
            },
        )

    async def fetch(self, item: DiscoveredItem) -> bytes:
        client = await self._require_client()
        if item.size and item.size > self._max_bytes:
            raise ConfigurationError(
                f"object {item.external_id!r} is {item.size} bytes, above the {self._max_bytes} byte limit"
            )
        return await asyncio.to_thread(self._get_object, client, item.external_id)

    def _get_object(self, client: Any, key: str) -> bytes:
        try:
            response = client.get_object(Bucket=self._bucket, Key=key)
            with response["Body"] as body:
                return body.read()
        except Exception as exc:  # noqa: BLE001 - botocore errors are dynamic
            raise ConnectionFailed(f"cannot read s3://{self._bucket}/{key}: {_reason(exc)}") from exc

    async def metadata(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "type": self.source_type.value,
            "bucket": self._bucket,
            "prefix": self._prefix,
            "endpoint_url": self.config("endpoint_url") or "https://s3.amazonaws.com",
            "region": self.config("region") or DEFAULT_REGION,
            "page_size": self._page_size,
            "connection": self.safe_connection(),
        }


def _cursor(token: str | None, last_key: str) -> str:
    """Checkpoint both the continuation token and the last key.

    The token resumes the current listing; the key survives token expiry because
    ``StartAfter`` can restart the listing exactly where it stopped.
    """
    return f"{token or ''}|{last_key}"


def _resume(cursor: str | None) -> tuple[str | None, str | None]:
    if not cursor:
        return None, None
    token, _, last_key = cursor.partition("|")
    return (token or None), (last_key or None)


def _reason(exc: BaseException) -> str:
    response = getattr(exc, "response", None)
    if isinstance(response, Mapping):
        error = response.get("Error") or {}
        code = error.get("Code")
        message = error.get("Message")
        if code:
            return f"{code}: {message}" if message else str(code)
    return str(exc)
