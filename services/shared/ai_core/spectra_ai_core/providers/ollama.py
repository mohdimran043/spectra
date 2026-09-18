"""Ollama providers over the native HTTP API (``/api/chat``, ``/api/tags``)."""

from __future__ import annotations

import base64
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

log = get_logger(__name__)

RUNTIME_NAME = "ollama"
CHAT_PATH = "/api/chat"
TAGS_PATH = "/api/tags"
GENERATE_PATH = "/api/generate"
# Ollama keeps a model resident on its own timer (5 minutes by default) in its
# own process.  Sending keep_alive=0 releases it immediately, which is what
# makes SPECTRA's eviction actually free VRAM rather than only forget about it.
UNLOAD_KEEP_ALIVE = 0
UNLOAD_TIMEOUT_SECONDS = 30.0
DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_VISION_PROMPT = "Describe this image factually. List any visible text and objects."
MAX_LISTED_MODELS = 8


def _normalise(name: str) -> str:
    """``qwen3:8b`` and ``qwen3:8b-instruct`` differ; ``llama3`` and ``llama3:latest`` do not."""
    return name[: -len(":latest")] if name.endswith(":latest") else name


class _OllamaBase(HttpProviderMixin):
    """Availability and request assembly shared by the chat and vision providers."""

    runtime_name = RUNTIME_NAME

    def __init__(self, model: str, device: str = "cuda", **options: Any) -> None:
        super().__init__(model, device, **options)  # type: ignore[call-arg]
        self.base_url = str(options.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
        self.call_timeout_seconds = float(options.get("timeout_seconds") or self.call_timeout_seconds)

    async def available(self) -> tuple[bool, str]:
        payload, error = await self.probe_json(f"{self.base_url}{TAGS_PATH}")
        if payload is None:
            return False, f"ollama unreachable: {error}"
        names = {_normalise(str(entry.get("name", ""))) for entry in payload.get("models", [])}
        names |= {_normalise(str(entry.get("model", ""))) for entry in payload.get("models", [])}
        names.discard("")
        if _normalise(self.model) in names:
            return True, f"ollama {self.base_url} has {self.model}"
        listed = ", ".join(sorted(names)[:MAX_LISTED_MODELS]) or "none"
        return False, f"ollama reachable but {self.model!r} is not pulled (present: {listed})"

    async def unload(self) -> None:
        """Release the model from ollama's process, then drop our client.

        Without the keep_alive=0 call the weights stay in VRAM on ollama's own
        timer, so evicting a role here would free nothing and the next model
        would contend for memory that SPECTRA believes it has already reclaimed.
        """
        await self._release_from_server()
        await self.aclose()
        await super().unload()  # type: ignore[misc]

    async def _release_from_server(self) -> None:
        url = f"{self.base_url}{GENERATE_PATH}"
        try:
            response = await self.client.post(
                url,
                json={"model": self.model, "keep_alive": UNLOAD_KEEP_ALIVE},
                timeout=UNLOAD_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            log.info("ollama.released", model=self.model)
        except Exception as exc:
            # A failed release is not fatal - the model simply expires on
            # ollama's own timer - but the scheduler's VRAM accounting will be
            # optimistic until it does, so say so.
            log.warning("ollama.release_failed", model=self.model, error=describe_http_error(exc, url))

    async def _chat(self, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{CHAT_PATH}"
        try:
            response = await self.client.post(url, json=body)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            raise RuntimeError(describe_http_error(exc, url)) from exc


class OllamaLLM(_OllamaBase, LLMProvider):
    """Chat completion via Ollama, with native JSON-schema and tool pass-through."""

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
        options: dict[str, Any] = {"temperature": temperature, "num_predict": max_tokens}
        if stop:
            options["stop"] = list(stop)
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [message.as_dict() for message in messages],
            "stream": False,
            "options": options,
        }
        # SPECTRA never surfaces chain-of-thought, so reasoning models are asked
        # to skip it: on a small token budget the monologue otherwise consumes
        # the whole response and leaves no answer.  Ollama ignores the key on
        # models that do not support it.
        body["think"] = bool(self.options.get("think", False))
        if json_schema is not None:
            body["format"] = json_schema
        if tools:
            body["tools"] = list(tools)
        started = time.perf_counter()
        payload = await self._chat(body)
        return self._to_result(payload, json_schema, (time.perf_counter() - started) * 1000.0)

    def _to_result(
        self, payload: dict[str, Any], json_schema: dict[str, Any] | None, latency_ms: float
    ) -> GenerationResult:
        message = payload.get("message") or {}
        text = str(message.get("content", ""))
        text, _had_reasoning = strip_reasoning(text)
        structured = _parse_structured(text) if json_schema is not None else None
        if message.get("tool_calls"):
            structured = {**(structured or {}), "tool_calls": message["tool_calls"]}
        reasoning_only = _had_reasoning and not text
        return GenerationResult(
            text=text,
            model=self.model,
            runtime=RUNTIME_NAME,
            latency_ms=latency_ms,
            prompt_tokens=int(payload.get("prompt_eval_count", 0) or 0),
            completion_tokens=int(payload.get("eval_count", 0) or 0),
            finish_reason=str(payload.get("done_reason", "stop") or "stop"),
            structured=structured,
            degraded=reasoning_only,
            degraded_reason=(
                "the model returned only an internal reasoning trace, which is never surfaced; "
                "no answer text was produced"
                if reasoning_only
                else None
            ),
        )


class OllamaVision(_OllamaBase, VisionProvider):
    """Image captioning via an Ollama multimodal model."""

    async def describe(
        self, image_bytes: bytes, prompt: str = "", *, max_tokens: int = 512
    ) -> VisionDescription:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        body = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": prompt or DEFAULT_VISION_PROMPT, "images": [encoded]}
            ],
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        started = time.perf_counter()
        payload = await self._chat(body)
        caption = str((payload.get("message") or {}).get("content", "")).strip()
        return VisionDescription(
            caption=caption,
            model=self.model,
            runtime=RUNTIME_NAME,
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )


def _parse_structured(text: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        log.warning("ollama.structured_parse_failed", preview=text[:120])
        return None
    return parsed if isinstance(parsed, dict) else {"value": parsed}
