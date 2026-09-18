"""SQL audit sink.

Every ``query_readonly`` call - success *or* failure - writes one audit row.
The default sink forwards to ``repository.record_sql_audit(...)``, but the sink
is injectable so the ingestion/test harness can capture rows without standing up
storage, and so a future deployment can tee the trail to a SIEM.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from spectra_config.logging import get_logger

from .credentials import redact

log = get_logger(__name__)


@runtime_checkable
class AuditSink(Protocol):
    """Anything that can persist one SQL audit record."""

    async def record(
        self,
        *,
        source_id: str,
        sql: str,
        params: Mapping[str, Any],
        user_id: str,
        rows: int,
        ok: bool,
        error: str | None,
    ) -> None: ...


class RepositoryAuditSink:
    """Writes to the relational repository via ``get_storage()``.

    Storage is resolved lazily on first use so importing this package never
    builds a storage bundle.
    """

    def __init__(self, repository: Any | None = None) -> None:
        self._repository = repository

    async def _resolve(self) -> Any:
        if self._repository is None:
            from spectra_storage.facade import get_storage

            storage = await get_storage()
            self._repository = storage.repository
        return self._repository

    async def record(
        self,
        *,
        source_id: str,
        sql: str,
        params: Mapping[str, Any],
        user_id: str,
        rows: int,
        ok: bool,
        error: str | None,
    ) -> None:
        repository = await self._resolve()
        await repository.record_sql_audit(
            source_id=source_id,
            sql=sql,
            params=dict(params),
            user_id=user_id,
            rows=rows,
            ok=ok,
            error=error,
        )


async def record_safely(
    sink: AuditSink,
    *,
    source_id: str,
    sql: str,
    params: Mapping[str, Any],
    user_id: str,
    rows: int,
    ok: bool,
    error: str | None,
) -> bool:
    """Write an audit row, logging (never raising) if the sink is unavailable.

    A failing audit sink must not turn a successful query into an exception for
    the analyst, but it is never swallowed silently either: the row is echoed to
    the structured log at error level so the trail survives in the log stream.
    """
    safe_params = redact(dict(params))
    try:
        await sink.record(
            source_id=source_id,
            sql=sql,
            params=dict(params),
            user_id=user_id,
            rows=rows,
            ok=ok,
            error=error,
        )
        return True
    except Exception as exc:  # noqa: BLE001 - the sink is infrastructure
        log.error(
            "sql.audit_write_failed",
            source_id=source_id,
            user_id=user_id,
            sql=sql,
            params=safe_params,
            rows=rows,
            ok=ok,
            query_error=error,
            error=str(exc),
        )
        return False
