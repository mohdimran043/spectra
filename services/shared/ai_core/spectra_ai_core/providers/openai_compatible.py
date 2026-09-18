"""OpenAI-shaped chat providers: vLLM, OpenAI itself, or any compatible endpoint."""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from typing import Any

from spectra_config.logging import get_logger

from ..interfaces import (
    ChatMessage,
    GenerationResult,
    LLMProvider,
    VisionDescription,
    VisionProvider,
)
from ..reasoning import strip_reasoning
from .http_base import HttpProviderMixin, describe_http_error
from .imaging import data_uri

log = get_logger(__name__)

RUNTIME_NAME = "openai_compatible"
MODELS_PATH = "/models"
CHAT_PATH = "/chat/completions"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
PUBLIC_OPENAI_HOST = "api.openai.com"
DEFAULT_VISION_PROMPT = "Describe this image factually. List any visible text and objects."
SCHEMA_RESPONSE_NAME = "spectra_structured_response"


class _OpenAICompatibleBase(HttpProviderMixin):
    """Shared auth, availability probe and POST for the chat-completions shape."""

    runtime_name = RUNTIME_NAME

    def __init__(self, model: str, device: str = "remote", **options: Any) -> None:
        super().__init__(model, device, **options)  # type: ignore[call-arg]
        self.base_url = str(options.get("base_url") or DEFAULT_OPENAI_BASE_URL).rstrip("/")
        self.api_key = str(options.get("api_key") or "")
        self.runtime_label = str(options.get("runtime_label") or RUNTIME_NAME)
        self.call_timeout_seconds = float(options.get("timeout_seconds") or self.call_timeout_seconds)

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def _requires_key(self) -> bool:
        return PUBLIC_OPENAI_HOST in self.base_url

    async def available(self) -> tuple[bool, str]:
        if self._requires_key() and not self.api_key:
            return False, f"{self.base_url} requires an API key but openai_api_key is empty"
        payload, error = await self.probe_json(f"{self.base_url}{MODELS_PATH}", self.headers)
        if payload is None:
            return False, f"{self.runtime_label} endpoint unreachable: {error}"
        served = {str(entry.get("id", "")) for entry in payload.get("data", []) if isinstance(entry, dict)}
        if served and self.model not in served:
            return False, f"{self.base_url} does not serve {self.model!r} (serves: {len(served)} models)"
        return True, f"{self.runtime_label} endpoint {self.base_url} serving {self.model}"

    async def unload(self) -> None:
        await self.aclose()
        await super().unload()  # type: ignore[misc]

    async def _post_chat(self, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{CHAT_PATH}"
        try:
            response = await self.client.post(url, json=body, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            raise RuntimeError(describe_http_error(exc, url)) from exc

    def _result(
        self, payload: dict[str, Any], want_structured: bool, latency_ms: float
    ) -> GenerationResult:
        choices = payload.get("choices") or [{}]
        message = choices[0].get("message") or {}
        text = str(message.get("content") or "")
        text, _had_reasoning = strip_reasoning(text)
        usage = payload.get("usage") or {}
        structured = _parse_structured(text) if want_structured else None
        if message.get("tool_calls"):
            structured = {**(structured or {}), "tool_calls": message["tool_calls"]}
        return GenerationResult(
            text=text,
            model=self.model,
            runtime=self.runtime_label,
            latency_ms=latency_ms,
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
            finish_reason=str(choices[0].get("finish_reason") or "stop"),
            structured=structured,
        )


class OpenAICompatibleLLM(_OpenAICompatibleBase, LLMProvider):
    """Chat completions against vLLM / OpenAI / any OpenAI-shaped server."""

    async def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        json_schema: dict[str, Any] | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
        stop: Sequence[str] | None = None,
    ) -> GenerationResult:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [message.as_dict() for message in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if stop:
            body["stop"] = list(stop)
        if tools:
            body["tools"] = list(tools)
        if json_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": SCHEMA_RESPONSE_NAME, "schema": json_schema, "strict": False},
            }
        started = time.perf_counter()
        payload = await self._post_chat(body)
        return self._result(payload, json_schema is not None, (time.perf_counter() - started) * 1000.0)


class OpenAICompatibleVision(_OpenAICompatibleBase, VisionProvider):
    """Vision through multi-part content with a base64 ``image_url``."""

    async def describe(
        self, image_bytes: bytes, prompt: str = "", *, max_tokens: int = 512
    ) -> VisionDescription:
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt or DEFAULT_VISION_PROMPT},
                        {"type": "image_url", "image_url": {"url": data_uri(image_bytes)}},
                    ],
                }
            ],
        }
        started = time.perf_counter()
        payload = await self._post_chat(body)
        result = self._result(payload, False, (time.perf_counter() - started) * 1000.0)
        return VisionDescription(
            caption=result.text.strip(),
            model=self.model,
            runtime=self.runtime_label,
            latency_ms=result.latency_ms,
        )


def _parse_structured(text: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        log.warning("openai_compatible.structured_parse_failed", preview=text[:120])
        return None
    return parsed if isinstance(parsed, dict) else {"value": parsed}
