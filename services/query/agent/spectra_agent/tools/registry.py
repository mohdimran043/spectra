"""Tool registry: availability, function-calling declarations and safe dispatch.

A tool whose ``requires_flag`` is disabled is *excluded* from the declarations
the planner sees.  Asking for it anyway returns a ToolResult that explains the
tool is switched off and names the enabled alternatives - never a crash, never a
fabricated result.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from spectra_config.logging import get_logger
from spectra_schemas import ToolResult, ToolSpec

from ..context import ToolContext
from .base import Tool

log = get_logger(__name__)

# What an analyst should reach for when a capability is switched off.  Every
# entry names a *real* tool; the registry filters it to the enabled ones.
ALTERNATIVES: dict[str, tuple[str, ...]] = {
    "search_images": ("search_documents", "search_videos", "query_database"),
    "search_videos": ("search_images", "search_documents", "search_audio"),
    "search_audio": ("search_documents", "search_videos"),
    "search_documents": ("query_database", "search_entities", "search_graph"),
    "query_database": ("search_documents", "search_entities"),
    "get_database_schema": ("query_database", "get_source_metadata"),
    "get_database_record": ("query_database", "search_documents"),
    "resolve_entity": ("search_entities", "search_documents"),
    "search_entities": ("resolve_entity", "search_documents"),
    "search_graph": ("search_entities", "search_documents"),
    "expand_graph": ("search_graph", "search_entities"),
    "get_image": ("get_source_metadata", "search_documents"),
    "get_video_timestamp": ("search_videos", "get_source_metadata"),
    "get_document_page": ("search_documents", "get_source_metadata"),
    "verify_claim": ("search_supporting_evidence", "detect_contradictions"),
    "detect_contradictions": ("search_disconfirming_evidence", "verify_claim"),
    "search_disconfirming_evidence": ("search_documents", "query_database"),
    "search_supporting_evidence": ("search_documents", "query_database"),
    "build_timeline": ("search_documents", "query_database"),
    "open_application_record": ("get_database_record", "query_database"),
}


class ToolRegistry:
    """Name -> :class:`Tool`, filtered by the deployment's agent flags."""

    def __init__(self, flags: Mapping[str, bool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        self._flags: dict[str, bool] = dict(flags or {})

    # -- registration -----------------------------------------------------
    def register(self, tool: Tool) -> None:
        if tool.spec.name in self._tools:
            raise ValueError(f"tool '{tool.spec.name}' is already registered")
        self._tools[tool.spec.name] = tool

    def register_all(self, tools: list[Tool]) -> None:
        for tool in tools:
            self.register(tool)

    # -- lookup -----------------------------------------------------------
    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all_specs(self) -> list[ToolSpec]:
        return [tool.spec for tool in self._tools.values()]

    def is_enabled(self, name: str, flags: Mapping[str, bool] | None = None) -> bool:
        tool = self._tools.get(name)
        if tool is None:
            return False
        flag = tool.spec.requires_flag
        if not flag:
            return True
        return bool(self._resolve_flags(flags).get(flag, True))

    def available(self, flags: Mapping[str, bool] | None = None) -> list[ToolSpec]:
        resolved = self._resolve_flags(flags)
        return [
            tool.spec
            for tool in self._tools.values()
            if not tool.spec.requires_flag or resolved.get(tool.spec.requires_flag, True)
        ]

    def available_names(self, flags: Mapping[str, bool] | None = None) -> list[str]:
        return [spec.name for spec in self.available(flags)]

    def declarations(self, flags: Mapping[str, bool] | None = None) -> list[dict[str, Any]]:
        """Function-calling schema list for the enabled tools only."""
        return [spec.openai_function() for spec in self.available(flags)]

    def alternatives_for(self, name: str, flags: Mapping[str, bool] | None = None) -> list[str]:
        enabled = set(self.available_names(flags))
        return [alt for alt in ALTERNATIVES.get(name, ()) if alt in enabled]

    # -- dispatch ---------------------------------------------------------
    async def call(
        self,
        name: str,
        args: dict[str, Any] | None,
        ctx: ToolContext,
        flags: Mapping[str, bool] | None = None,
    ) -> ToolResult:
        resolved = self._resolve_flags(flags or ctx.agent_flags)
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                tool=name,
                ok=False,
                error=f"unknown tool '{name}'; available tools: {self.available_names(resolved)}",
                summary=f"unknown tool '{name}'",
            )
        if not self.is_enabled(name, resolved):
            return self._disabled_result(tool.spec, resolved)
        return await tool.run(args, ctx)

    def _disabled_result(self, spec: ToolSpec, flags: Mapping[str, bool]) -> ToolResult:
        alternatives = self.alternatives_for(spec.name, flags)
        reason = (
            f"tool '{spec.name}' is disabled because the '{spec.requires_flag}' agent "
            f"is switched off in this deployment"
        )
        log.info("tool.disabled", tool=spec.name, flag=spec.requires_flag)
        return ToolResult(
            tool=spec.name,
            ok=False,
            error=f"{reason}. Enabled alternatives: {alternatives or ['none']}",
            summary=reason,
            degraded=True,
            degraded_reason=reason,
            data={"alternatives": alternatives, "requires_flag": spec.requires_flag},
        )

    def _resolve_flags(self, flags: Mapping[str, bool] | None) -> dict[str, bool]:
        if flags is None:
            return dict(self._flags)
        merged = dict(self._flags)
        merged.update(flags)
        return merged
