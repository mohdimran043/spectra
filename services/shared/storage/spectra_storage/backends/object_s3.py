"""S3 / MinIO object store (distributed profile).

boto3 is synchronous, so every call is pushed onto a worker thread rather than
blocking the event loop.  ``local_path`` materialises the blob into a cache
directory under ``runtime_dir`` because ffmpeg, PySceneDetect and the OCR engines
all need a real file on disk, and re-downloading a 500 MB video per tool call
would dominate investigation latency.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from spectra_config import Settings
from spectra_config.logging import get_logger

from ..interfaces import ObjectStore
from ..object_uris import ObjectRef, parse_object_uri, resolve_within

log = get_logger(__name__)

OBJECT_CACHE_DIRNAME = "objcache"
NOT_FOUND_CODES = frozenset({"404", "NoSuchKey", "NoSuchBucket", "NotFound"})
CONNECT_TIMEOUT_SECONDS = 5
READ_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 3


class S3ObjectStore(ObjectStore):
    """Blobs in an S3-compatible bucket (AWS S3 or MinIO via ``endpoint_url``)."""

    backend_name = "s3"

    def __init__(self, settings: Settings) -> None:
        import boto3  # lazy: optional dependency
        from botocore.config import Config  # lazy

        self._settings = settings
        self._bucket = settings.minio_bucket
        self._cache_root = Path(settings.runtime_dir) / OBJECT_CACHE_DIRNAME
        self._cache_root.mkdir(parents=True, exist_ok=True)
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.minio_endpoint or None,
            aws_access_key_id=settings.minio_access_key or None,
            aws_secret_access_key=settings.minio_secret_key or None,
            region_name=settings.minio_region or None,
            config=Config(
                connect_timeout=CONNECT_TIMEOUT_SECONDS,
                read_timeout=READ_TIMEOUT_SECONDS,
                retries={"max_attempts": MAX_RETRY_ATTEMPTS},
            ),
        )

    # -- lifecycle --------------------------------------------------------
    async def probe(self) -> None:
        """Verify the bucket exists (creating it when permitted) at start-up."""
        try:
            await asyncio.to_thread(self._client.head_bucket, Bucket=self._bucket)
        except Exception as exc:  # bucket may simply not exist yet
            if not _is_missing(exc):
                raise
            log.info("object.bucket_create", backend=self.backend_name, bucket=self._bucket)
            await asyncio.to_thread(self._client.create_bucket, Bucket=self._bucket)

    async def close(self) -> None:
        await asyncio.to_thread(self._client.close)

    # -- writes -----------------------------------------------------------
    async def put(self, uri: str, data: bytes, media_type: str = "application/octet-stream") -> str:
        ref = parse_object_uri(uri)
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=ref.key,
            Body=data,
            ContentType=media_type,
        )
        log.debug("object.put", backend=self.backend_name, uri=ref.uri, bytes=len(data))
        return ref.uri

    async def delete(self, uri: str) -> bool:
        ref = parse_object_uri(uri)
        if not await self._head(ref):
            return False
        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=ref.key)
        return True

    # -- reads ------------------------------------------------------------
    async def get(self, uri: str) -> bytes:
        ref = parse_object_uri(uri)
        try:
            response = await asyncio.to_thread(
                self._client.get_object, Bucket=self._bucket, Key=ref.key
            )
        except Exception as exc:
            if _is_missing(exc):
                raise FileNotFoundError(f"object {ref.uri} is not present in bucket {self._bucket}") from exc
            raise
        return await asyncio.to_thread(response["Body"].read)

    async def exists(self, uri: str) -> bool:
        return await self._head(parse_object_uri(uri))

    async def local_path(self, uri: str) -> str:
        ref = parse_object_uri(uri)
        target = resolve_within(self._cache_root, ref)
        if target.exists():
            return str(target)
        payload = await self.get(ref.uri)
        await asyncio.to_thread(_write_cache, target, payload)
        log.debug("object.cached", backend=self.backend_name, uri=ref.uri, path=str(target))
        return str(target)

    async def health(self) -> dict[str, Any]:
        try:
            await asyncio.to_thread(self._client.head_bucket, Bucket=self._bucket)
        except Exception as exc:  # health must never raise
            log.warning("object.health_failed", backend=self.backend_name, error=str(exc))
            return {"backend": self.backend_name, "status": "error", "detail": str(exc)}
        return {
            "backend": self.backend_name,
            "status": "ok",
            "endpoint": self._settings.minio_endpoint,
            "bucket": self._bucket,
        }

    async def _head(self, ref: ObjectRef) -> bool:
        try:
            await asyncio.to_thread(self._client.head_object, Bucket=self._bucket, Key=ref.key)
        except Exception as exc:
            if _is_missing(exc):
                return False
            raise
        return True


def _write_cache(target: Path, payload: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)


def _is_missing(exc: Exception) -> bool:
    """True when a botocore error means 'no such key/bucket' rather than a fault."""
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    error = response.get("Error", {})
    status = str(response.get("ResponseMetadata", {}).get("HTTPStatusCode", ""))
    return str(error.get("Code", "")) in NOT_FOUND_CODES or status == "404"
