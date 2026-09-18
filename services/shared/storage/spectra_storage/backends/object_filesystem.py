"""Filesystem object store - the embedded blob backend.

Maps ``spectra://objects/ab/<sha>.<ext>`` onto ``<object_root>/ab/<sha>.<ext>``.
Writes are atomic (temp file plus ``os.replace``) because ingestion and search
run concurrently and a half-written PDF served to the OCR agent would surface as
an unexplained extraction failure rather than an obvious IO error.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import Any

from spectra_config import Settings
from spectra_config.logging import get_logger

from ..interfaces import ObjectStore
from ..object_uris import parse_object_uri, resolve_within

log = get_logger(__name__)

TEMP_SUFFIX = ".partial"


class FilesystemObjectStore(ObjectStore):
    """Content-addressed blobs on the local filesystem."""

    backend_name = "filesystem"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._root = Path(settings.object_root)
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def _path_for(self, uri: str) -> Path:
        return resolve_within(self._root, parse_object_uri(uri))

    # -- writes -----------------------------------------------------------
    async def put(self, uri: str, data: bytes, media_type: str = "application/octet-stream") -> str:
        ref = parse_object_uri(uri)
        path = resolve_within(self._root, ref)
        await asyncio.to_thread(_write_atomic, path, data)
        log.debug(
            "object.put",
            backend=self.backend_name,
            uri=ref.uri,
            bytes=len(data),
            media_type=media_type,
        )
        return ref.uri

    async def delete(self, uri: str) -> bool:
        path = self._path_for(uri)

        def _remove() -> bool:
            if not path.exists():
                return False
            path.unlink()
            return True

        return await asyncio.to_thread(_remove)

    # -- reads ------------------------------------------------------------
    async def get(self, uri: str) -> bytes:
        path = self._path_for(uri)

        def _read() -> bytes:
            if not path.exists():
                raise FileNotFoundError(f"object {uri} is not present at {path}")
            return path.read_bytes()

        return await asyncio.to_thread(_read)

    async def exists(self, uri: str) -> bool:
        path = self._path_for(uri)
        return await asyncio.to_thread(path.exists)

    async def local_path(self, uri: str) -> str:
        path = self._path_for(uri)
        if not await asyncio.to_thread(path.exists):
            raise FileNotFoundError(f"object {uri} is not present at {path}")
        return str(path)

    async def health(self) -> dict[str, Any]:
        try:
            usage = await asyncio.to_thread(shutil.disk_usage, self._root)
        except OSError as exc:
            log.warning("object.health_failed", backend=self.backend_name, error=str(exc))
            return {"backend": self.backend_name, "status": "error", "detail": str(exc)}
        return {
            "backend": self.backend_name,
            "status": "ok",
            "root": str(self._root),
            "free_bytes": usage.free,
        }


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}{TEMP_SUFFIX}")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()

