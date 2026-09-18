"""The tool contract: validate, time-box, instrument, never raise.

``Tool.run`` is the wrapper every tool call goes through.  It validates the
arguments against the tool's own declared JSON schema, enforces
``spec.timeout_seconds``, serialises GPU-heavy work behind the single-GPU
semaphore, records latency, and converts *any* failure into a
``ToolResult(ok=False, error=...)`` so one broken source can never take an
investigation down.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from time import perf_counter
from typing import Any

from spectra_config.logging import get_logger, tool_call_id_var
from spectra_schemas import ToolError, ToolResult, ToolSpec, call_id

from ..context import ToolContext
from ..gpu import GpuScheduler
from .validation import validate_args

log = get_logger(__name__)


class Tool(ABC):
    """One callable capability exposed to the Brain."""

    spec: ToolSpec

    @property
    def name(self) -> str:
        return self.spec.name

    async def run(self, args: dict[str, Any] | None, ctx: ToolContext) -> ToolResult:
        """Validated, time-boxed, instrumented invocation.  Never raises."""
        started = perf_counter()
        token = tool_call_id_var.set(call_id())
        try:
            result = await self._guarded(args, ctx)
        finally:
            tool_call_id_var.reset(token)
        latency_ms = round((perf_counter() - started) * 1000, 3)
        log.info(
            "tool.finished",
            tool=self.spec.name,
            ok=result.ok,
            count=result.count,
            latency_ms=latency_ms,
            investigation_id=ctx.investigation_id,
        )
        return result.model_copy(update={"latency_ms": latency_ms})

    async def _guarded(self, args: dict[str, Any] | None, ctx: ToolContext) -> ToolResult:
        try:
            cleaned = validate_args(self.spec.name, self.spec.input_schema, args)
        except ToolError as exc:
            return self.failure(f"invalid arguments: {exc.message}")
        try:
            return await asyncio.wait_for(
                self._dispatch(cleaned, ctx), timeout=self.spec.timeout_seconds
            )
        except asyncio.TimeoutError:
            return self.failure(
                f"timed out after {self.spec.timeout_seconds:.1f}s", degraded=True
            )
        except ToolError as exc:
            return self.failure(exc.message, degraded=exc.degraded)
        except asyncio.CancelledError:  # pragma: no cover - cooperative shutdown
            raise
        except Exception as exc:
            log.exception("tool.failed", tool=self.spec.name, error=str(exc))
            return self.failure(f"{type(exc).__name__}: {exc}")

    async def _dispatch(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        if not self.spec.gpu_heavy:
            return await self.execute(args, ctx)
        async with GpuScheduler.slot(self.spec.name):
            return await self.execute(args, ctx)

    @abstractmethod
    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Tool body.  May raise ``ToolError``; ``run`` converts it."""

    # -- result helpers ---------------------------------------------------
    def success(
        self,
        *,
        data: dict[str, Any] | None = None,
        summary: str,
        count: int = 0,
        evidence_ids: list[str] | None = None,
        degraded: bool = False,
        degraded_reason: str | None = None,
    ) -> ToolResult:
        return ToolResult(
            tool=self.spec.name,
            ok=True,
            data=data or {},
            summary=summary,
            count=count,
            evidence_ids=evidence_ids or [],
            degraded=degraded,
            degraded_reason=degraded_reason,
        )

    def empty(self, summary: str) -> ToolResult:
        return ToolResult(tool=self.spec.name, ok=True, summary=summary, count=0)

    def failure(self, message: str, *, degraded: bool = False) -> ToolResult:
        return ToolResult(
            tool=self.spec.name,
            ok=False,
            error=message,
            summary=message,
            degraded=degraded,
            degraded_reason=message if degraded else None,
        )


def require_service(ctx: ToolContext, attribute: str, tool: str) -> Any:
    """Fetch an injected service or fail loudly - never silently substitute."""
    service = getattr(ctx.services, attribute, None)
    if service is None:
        raise ToolError(
            tool,
            f"the {attribute} service is not available in this deployment",
            degraded=True,
        )
    return service
