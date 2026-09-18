"""Model provider protocols.

The agent asks for a *capability* ("embed this", "caption that", "plan this
investigation").  It never names a model, a runtime or a device.  That
indirection is what makes the 24 GB sequential-scheduling story possible, and
what lets the same code target llama.cpp, vLLM, Ollama or a remote endpoint.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class GenerationResult:
    text: str
    model: str
    runtime: str
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    finish_reason: str = "stop"
    structured: dict[str, Any] | None = None
    degraded: bool = False
    degraded_reason: str | None = None


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    model: str
    runtime: str
    dimension: int
    latency_ms: float = 0.0
    degraded: bool = False
    degraded_reason: str | None = None


@dataclass(frozen=True)
class RerankResult:
    scores: list[float]
    model: str
    runtime: str
    latency_ms: float = 0.0
    degraded: bool = False
    degraded_reason: str | None = None


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str
    speaker: str | None = None
    confidence: float = 1.0


@dataclass(frozen=True)
class TranscriptionResult:
    segments: list[TranscriptSegment]
    language: str = "en"
    duration: float = 0.0
    model: str = ""
    runtime: str = ""
    latency_ms: float = 0.0
    degraded: bool = False
    degraded_reason: str | None = None

    @property
    def text(self) -> str:
        return " ".join(s.text.strip() for s in self.segments).strip()


@dataclass(frozen=True)
class OCRLine:
    text: str
    confidence: float = 1.0
    bbox: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class OCRResult:
    lines: list[OCRLine] = field(default_factory=list)
    engine: str = ""
    latency_ms: float = 0.0
    degraded: bool = False
    degraded_reason: str | None = None

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines).strip()


@dataclass(frozen=True)
class VisionDescription:
    caption: str
    detected_text: str = ""
    objects: list[str] = field(default_factory=list)
    model: str = ""
    runtime: str = ""
    latency_ms: float = 0.0
    degraded: bool = False
    degraded_reason: str | None = None


class BaseProvider(ABC):
    """Common lifecycle for every provider: load / unload / health."""

    runtime_name: str = "abstract"

    def __init__(self, model: str, device: str = "auto", **options: Any) -> None:
        self.model = model
        self.device = device
        self.options = options
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @abstractmethod
    async def available(self) -> tuple[bool, str]:
        """(reachable, reason) - checked before this candidate is selected."""

    async def load(self) -> None:
        self._loaded = True

    async def unload(self) -> None:
        self._loaded = False

    async def health(self) -> dict[str, Any]:
        ok, reason = await self.available()
        return {"runtime": self.runtime_name, "model": self.model, "ok": ok, "detail": reason}


class LLMProvider(BaseProvider):
    @abstractmethod
    async def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        json_schema: dict[str, Any] | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
        stop: Sequence[str] | None = None,
    ) -> GenerationResult: ...


class VisionProvider(BaseProvider):
    @abstractmethod
    async def describe(
        self, image_bytes: bytes, prompt: str = "", *, max_tokens: int = 512
    ) -> VisionDescription: ...


class EmbeddingProvider(BaseProvider):
    dimension: int = 512

    @abstractmethod
    async def embed_texts(self, texts: Sequence[str], *, is_query: bool = False) -> EmbeddingResult: ...

    async def embed_images(self, images: Sequence[bytes]) -> EmbeddingResult:
        raise NotImplementedError(f"{self.runtime_name} does not embed images")


class RerankerProvider(BaseProvider):
    @abstractmethod
    async def rerank(self, query: str, documents: Sequence[str]) -> RerankResult: ...


class SpeechProvider(BaseProvider):
    @abstractmethod
    async def transcribe(
        self, audio_path: str, *, language: str | None = None, diarize: bool = False
    ) -> TranscriptionResult: ...


class OCRProvider(BaseProvider):
    @abstractmethod
    async def read(self, image_bytes: bytes) -> OCRResult: ...
