"""Local folder connector.

Walks a configured root (default ``settings.data_dir/sources``) and streams one
:class:`DiscoveredItem` per file.

Path confinement is the security property here: *every* path - discovered or
requested - is resolved and checked against the resolved root, so a symlink that
points outside the root, an absolute path and a ``../../etc/passwd`` style
relative path are all refused.  ``Path.resolve()`` follows symlinks before the
check, which is what makes the symlink case fail rather than escape.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

from spectra_config import Settings, get_settings
from spectra_config.logging import get_logger
from spectra_schemas.catalog import SourceDescriptor, SourceHealth
from spectra_schemas.enums import SourceStatus, SourceType

from .base import Checkpoint, DiscoveredItem, SourceConnector
from .credentials import CredentialStore
from .errors import ConfigurationError, PathTraversalError
from .media import classify

log = get_logger(__name__)

#: How many files ``validate()`` counts before reporting - health must stay cheap.
HEALTH_SCAN_LIMIT = 5_000
#: Directory entries pulled per worker-thread hop while streaming discovery.
SCAN_BATCH_SIZE = 256


class LocalFolderConnector(SourceConnector):
    """Streams files from a confined local directory tree."""

    source_type: ClassVar[SourceType] = SourceType.LOCAL_FOLDER

    def __init__(
        self,
        descriptor: SourceDescriptor,
        credentials: CredentialStore | None = None,
        *,
        settings: Settings | None = None,
    ) -> None:
        super().__init__(descriptor, credentials)
        self._settings = settings or get_settings()
        self._root = self._resolve_root()
        self._include_hidden = bool(self.config("include_hidden", False))
        self._extensions = _as_extensions(self.config("extensions"))
        self._max_bytes = int(self.config("max_bytes", self._settings.max_upload_bytes))
        self._since = _as_timestamp(self._checkpoint.cursor)

    def _default_root(self) -> Path:
        return Path(self._settings.data_dir) / "sources"

    def _resolve_root(self) -> Path:
        raw = self.config("root")
        root = Path(str(raw)).expanduser() if raw else self._default_root()
        return root.resolve()

    @property
    def root(self) -> Path:
        return self._root

    # -- path confinement -------------------------------------------------
    def resolve_within_root(self, candidate: str | Path) -> Path:
        """Resolve ``candidate`` inside the root or raise :class:`PathTraversalError`.

        The check runs *after* ``resolve()``, so symlinks that leave the root are
        rejected along with ``..`` traversal and absolute paths.
        """
        raw = Path(str(candidate)).expanduser()
        if raw.is_absolute():
            resolved = raw.resolve()
        else:
            if ".." in raw.parts:
                raise PathTraversalError(f"path escapes the source root: {candidate!r}")
            resolved = (self._root / raw).resolve()
        if resolved != self._root and not resolved.is_relative_to(self._root):
            raise PathTraversalError(
                f"path {str(candidate)!r} resolves outside the source root {self._root}"
            )
        return resolved

    # -- lifecycle --------------------------------------------------------
    async def connect(self) -> None:
        if not self._root.exists():
            raise ConfigurationError(f"source root does not exist: {self._root}")
        if not self._root.is_dir():
            raise ConfigurationError(f"source root is not a directory: {self._root}")
        self._connected = True

    async def validate(self) -> SourceHealth:
        started = time.perf_counter()
        try:
            await self.connect()
            count = await asyncio.to_thread(self._count_files)
        except Exception as exc:  # noqa: BLE001 - health must never raise
            log.warning("local_folder.validate_failed", source_id=self.source_id, error=str(exc))
            return self._health(SourceStatus.UNREACHABLE, detail=str(exc), started=started)
        if not os.access(self._root, os.R_OK):
            return self._health(
                SourceStatus.DEGRADED, detail=f"root is not readable: {self._root}", started=started
            )
        return self._health(
            SourceStatus.HEALTHY,
            detail=f"{count}{'+' if count >= HEALTH_SCAN_LIMIT else ''} file(s) under {self._root}",
            started=started,
            asset_count=count,
        )

    def _count_files(self) -> int:
        count = 0
        for _ in self._iter_files():
            count += 1
            if count >= HEALTH_SCAN_LIMIT:
                break
        return count

    async def discover(self) -> AsyncIterator[DiscoveredItem]:
        """Stream every file under the root, newest-modified filter applied.

        The walk is lazy: directories are scanned with ``os.scandir`` and each
        file is yielded as it is found, so a root with millions of files costs
        one directory entry of memory at a time.
        """
        await self.connect()
        walker = self._iter_files()
        latest = self._since
        while True:
            batch = await asyncio.to_thread(_take, walker, SCAN_BATCH_SIZE)
            if not batch:
                return
            for path, stat_result in batch:
                modified = stat_result.st_mtime
                if self._since is not None and modified <= self._since:
                    continue
                latest = modified if latest is None else max(latest, modified)
                self._record_checkpoint(_as_cursor(latest), added=1)
                yield self._item(path, stat_result)

    def _iter_files(self) -> Iterator[tuple[Path, os.stat_result]]:
        stack: list[Path] = [self._root]
        while stack:
            current = stack.pop()
            try:
                entries = list(os.scandir(current))
            except OSError as exc:
                log.warning("local_folder.scan_failed", path=str(current), error=str(exc))
                continue
            for entry in entries:
                yield from self._classify_entry(entry, stack)

    def _classify_entry(self, entry: os.DirEntry[str], stack: list[Path]) -> Iterator[tuple[Path, os.stat_result]]:
        name = entry.name
        if not self._include_hidden and name.startswith("."):
            return
        try:
            path = self.resolve_within_root(entry.path)
        except PathTraversalError:
            log.warning("local_folder.path_rejected", source_id=self.source_id, path=entry.path)
            return
        try:
            if entry.is_dir(follow_symlinks=False) or (entry.is_dir() and path.is_dir()):
                stack.append(path)
                return
            if not entry.is_file():
                return
            stat_result = path.stat()
        except OSError as exc:
            log.warning("local_folder.stat_failed", path=str(path), error=str(exc))
            return
        if self._extensions and path.suffix.lower() not in self._extensions:
            return
        yield path, stat_result

    def _item(self, path: Path, stat_result: os.stat_result) -> DiscoveredItem:
        relative = path.relative_to(self._root).as_posix()
        media_type, kind = classify(path.name)
        return DiscoveredItem(
            external_id=relative,
            name=path.name,
            media_type=media_type,
            size=stat_result.st_size,
            modified_at=datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc),
            kind=kind,
            extra={"relative_path": relative, "root": str(self._root)},
        )

    async def fetch(self, item: DiscoveredItem) -> bytes:
        path = self.resolve_within_root(item.external_id)
        size = await asyncio.to_thread(lambda: path.stat().st_size)
        if size > self._max_bytes:
            raise ConfigurationError(
                f"file {item.external_id!r} is {size} bytes, above the {self._max_bytes} byte limit"
            )
        return await asyncio.to_thread(path.read_bytes)

    async def metadata(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "type": self.source_type.value,
            "root": str(self._root),
            "include_hidden": self._include_hidden,
            "extensions": sorted(self._extensions) if self._extensions else None,
            "max_bytes": self._max_bytes,
            "connection": self.safe_connection(),
        }

    async def restore(self, checkpoint: Checkpoint) -> None:
        await super().restore(checkpoint)
        self._since = _as_timestamp(checkpoint.cursor)


class UploadConnector(LocalFolderConnector):
    """Files an analyst uploaded through the API - same confinement rules."""

    source_type: ClassVar[SourceType] = SourceType.UPLOAD

    def _default_root(self) -> Path:
        return Path(self._settings.upload_dir)


def _take(iterator: Iterator[tuple[Path, os.stat_result]], count: int) -> list[tuple[Path, os.stat_result]]:
    """Pull at most ``count`` entries - bounds the memory one thread hop uses."""
    batch: list[tuple[Path, os.stat_result]] = []
    for entry in iterator:
        batch.append(entry)
        if len(batch) >= count:
            break
    return batch


def _as_extensions(value: Any) -> frozenset[str]:
    if not value:
        return frozenset()
    if isinstance(value, str):
        value = [value]
    return frozenset(
        item if str(item).startswith(".") else f".{item}" for item in (str(v).lower() for v in value)
    )


def _as_timestamp(cursor: str | None) -> float | None:
    if not cursor:
        return None
    try:
        return float(cursor)
    except ValueError:
        try:
            return datetime.fromisoformat(cursor).timestamp()
        except ValueError:
            log.warning("local_folder.bad_checkpoint", cursor=cursor)
            return None


def _as_cursor(timestamp: float | None) -> str | None:
    return None if timestamp is None else f"{timestamp:.6f}"
