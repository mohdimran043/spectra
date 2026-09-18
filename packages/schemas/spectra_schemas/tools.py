"""Agent tool contracts - name, JSON schema, validation, timeout, telemetry."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .enums import AgentName


class ToolSpec(BaseModel):
    """Declarative description of a callable tool, exposed to the Brain."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    agent: AgentName
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    timeout_seconds: float = 30.0
    gpu_heavy: bool = False
    requires_flag: str | None = Field(
        default=None, description="Agent flag that must be enabled for this tool"
    )
    cost_hint: float = 1.0

    def openai_function(self) -> dict[str, Any]:
        """Render as an OpenAI/Qwen-style function-calling declaration."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str
    ok: bool = True
    data: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    count: int = 0
    evidence_ids: list[str] = Field(default_factory=list)
    error: str | None = None
    degraded: bool = False
    degraded_reason: str | None = None
    latency_ms: float = 0.0


class ToolError(Exception):
    """Raised by a tool when it cannot fulfil a valid request."""

    def __init__(self, tool: str, message: str, *, degraded: bool = False) -> None:
        super().__init__(message)
        self.tool = tool
        self.message = message
        self.degraded = degraded
