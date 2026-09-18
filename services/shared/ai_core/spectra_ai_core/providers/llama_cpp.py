"""llama.cpp providers.

Both the ``llama_cpp`` python package *and* the GGUF file must be present; when
either is missing :meth:`available` explains which one, and the runtime manager
simply moves to the next candidate.  Every llama.cpp call is blocking, so it is
dispatched to a worker thread.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import time
from collections.abc import Sequence
from pathlib import Path
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
from .imaging import data_uri

log = get_logger(__name__)

RUNTIME_NAME = "llama_cpp"
PACKAGE_NAME = "llama_cpp"
GGUF_SUFFIX = ".gguf"
MMPROJ_MARKER = "mmproj"
DEFAULT_CONTEXT_TOKENS = 8192
MIN_CONTEXT_TOKENS = 1024
ALL_LAYERS_ON_GPU = -1
DEFAULT_VISION_PROMPT = "Describe this image factually. List any visible text and objects."


def _find_gguf(model_dir: Path, filename: str) -> Path | None:
    direct = model_dir / filename
    if direct.is_file():
        return direct
    if not model_dir.is_dir():
        return None
    return next((path for path in sorted(model_dir.rglob(filename)) if path.is_file()), None)


def _find_mmproj(model_dir: Path) -> Path | None:
    if not model_dir.is_dir():
        return None
    candidates = (path for path in sorted(model_dir.rglob(f"*{GGUF_SUFFIX}")) if MMPROJ_MARKER in path.name.lower())
    return next(candidates, None)


class _LlamaCppBase:
    """Weight discovery, lazy construction and thread dispatch."""

    runtime_name = RUNTIME_NAME

    def __init__(self, model: str, device: str = "cuda", **options: Any) -> None:
        super().__init__(model, device, **options)  # type: ignore[call-arg]
        self.model_dir = Path(options.get("model_dir") or ".")
        self.context_tokens = int(options.get("context_tokens") or DEFAULT_CONTEXT_TOKENS)
        self._llama: Any | None = None

    @property
    def weights_path(self) -> Path | None:
        return _find_gguf(self.model_dir, self.model)

    async def available(self) -> tuple[bool, str]:
        if importlib.util.find_spec(PACKAGE_NAME) is None:
            return False, f"{PACKAGE_NAME} package is not installed"
        path = self.weights_path
        if path is None:
            return False, f"GGUF {self.model!r} not found under {self.model_dir}"
        return True, f"{PACKAGE_NAME} with {path}"

    def _gpu_layers(self) -> int:
        return ALL_LAYERS_ON_GPU if self.device == "cuda" else 0

    def _build_kwargs(self) -> dict[str, Any]:
        return {
            "model_path": str(self.weights_path),
            "n_ctx": self.context_tokens,
            "n_gpu_layers": self._gpu_layers(),
            "verbose": False,
        }

    async def load(self) -> None:
        if self._llama is not None:
            return
        ok, reason = await self.available()
        if not ok:
            raise RuntimeError(f"cannot load {self.model}: {reason}")
        self._llama = await asyncio.to_thread(self._construct)
        await super().load()  # type: ignore[misc]
        log.info("llama_cpp.loaded", model=self.model, device=self.device, n_ctx=self.context_tokens)

    def _construct(self) -> Any:
        from llama_cpp import Llama

        return Llama(**self._build_kwargs())

    async def unload(self) -> None:
        llama, self._llama = self._llama, None
        if llama is not None:
            await asyncio.to_thread(_close_quietly, llama)
        await super().unload()  # type: ignore[misc]

    async def _chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        await self.load()
        llama = self._llama
        if llama is None:  # pragma: no cover - load() raises first
            raise RuntimeError(f"{self.model} is not loaded")
        return await asyncio.to_thread(lambda: llama.create_chat_completion(**payload))


def _close_quietly(llama: Any) -> None:
    closer = getattr(llama, "close", None)
    if callable(closer):
        closer()


class LlamaCppLLM(_LlamaCppBase, LLMProvider):
    """Local GGUF chat completion."""

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
        payload: dict[str, Any] = {
            "messages": [message.as_dict() for message in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if stop:
            payload["stop"] = list(stop)
        if tools:
            payload["tools"] = list(tools)
        if json_schema is not None:
            payload["response_format"] = {"type": "json_object", "schema": json_schema}
        started = time.perf_counter()
        response = await self._chat(payload)
        return self._to_result(response, json_schema, (time.perf_counter() - started) * 1000.0)

    def _to_result(
        self, response: dict[str, Any], json_schema: dict[str, Any] | None, latency_ms: float
    ) -> GenerationResult:
        choice = (response.get("choices") or [{}])[0]
        text = str((choice.get("message") or {}).get("content") or "")
        text, _had_reasoning = strip_reasoning(text)
        usage = response.get("usage") or {}
        return GenerationResult(
            text=text,
            model=self.model,
            runtime=RUNTIME_NAME,
            latency_ms=latency_ms,
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
            finish_reason=str(choice.get("finish_reason") or "stop"),
            structured=_safe_json(text) if json_schema is not None else None,
        )


class LlamaCppVision(_LlamaCppBase, VisionProvider):
    """Local GGUF vision-language model.  Requires a companion ``mmproj`` projector."""

    async def available(self) -> tuple[bool, str]:
        ok, reason = await super().available()
        if not ok:
            return ok, reason
        if _find_mmproj(self.model_dir) is None:
            return False, f"GGUF found but no *{MMPROJ_MARKER}*{GGUF_SUFFIX} projector under {self.model_dir}"
        return True, reason

    def _construct(self) -> Any:
        from llama_cpp import Llama
        from llama_cpp.llama_chat_format import Llava15ChatHandler

        projector = _find_mmproj(self.model_dir)
        handler = Llava15ChatHandler(clip_model_path=str(projector), verbose=False)
        return Llama(**self._build_kwargs(), chat_handler=handler)

    async def describe(
        self, image_bytes: bytes, prompt: str = "", *, max_tokens: int = 512
    ) -> VisionDescription:
        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt or DEFAULT_VISION_PROMPT},
                        {"type": "image_url", "image_url": {"url": data_uri(image_bytes)}},
                    ],
                }
            ],
            "max_tokens": max_tokens,
        }
        started = time.perf_counter()
        response = await self._chat(payload)
        choice = (response.get("choices") or [{}])[0]
        return VisionDescription(
            caption=str((choice.get("message") or {}).get("content") or "").strip(),
            model=self.model,
            runtime=RUNTIME_NAME,
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )


def _safe_json(text: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else {"value": parsed}
