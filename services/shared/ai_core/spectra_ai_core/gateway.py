"""Model Gateway - the only door to any model in SPECTRA.

Responsibilities live behind this facade:

* a **registry** of roles -> candidate implementations (``resources/models.yaml``)
* a **runtime manager** doing lazy load, VRAM accounting, sequential GPU
  scheduling, idle eviction, OOM recovery and CPU fallback
* **degraded-mode reporting** so the UI can say *why* something is unavailable

Callers ask for a capability, never for a model:

    gateway = await get_gateway()
    result  = await gateway.embed_texts(["hello"])
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from spectra_config import Settings, get_settings
from spectra_schemas import ModelRole, ModelRuntimeStatus

from .interfaces import (
    ChatMessage,
    EmbeddingResult,
    GenerationResult,
    OCRResult,
    RerankResult,
    TranscriptionResult,
    VisionDescription,
)


class ModelGateway(ABC):
    """Capability-oriented interface over every model role."""

    # -- text generation --------------------------------------------------
    @abstractmethod
    async def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        role: ModelRole = ModelRole.DEEP_BRAIN,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        json_schema: dict[str, Any] | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> GenerationResult:
        """Generate text.  Falls back to ``fallback_role`` then to the
        deterministic provider, always reporting ``degraded`` when it does."""

    # -- embeddings -------------------------------------------------------
    @abstractmethod
    async def embed_texts(self, texts: Sequence[str], *, is_query: bool = False) -> EmbeddingResult: ...

    @abstractmethod
    async def embed_images(self, images: Sequence[bytes]) -> EmbeddingResult: ...

    @abstractmethod
    async def embed_text_for_image_space(self, texts: Sequence[str]) -> EmbeddingResult:
        """Embed text into the *multimodal* space for text->image retrieval."""

    # -- reranking --------------------------------------------------------
    @abstractmethod
    async def rerank(self, query: str, documents: Sequence[str]) -> RerankResult: ...

    # -- vision / speech / ocr -------------------------------------------
    @abstractmethod
    async def describe_image(self, image_bytes: bytes, prompt: str = "") -> VisionDescription: ...

    @abstractmethod
    async def transcribe(
        self, audio_path: str, *, language: str | None = None, diarize: bool = False
    ) -> TranscriptionResult: ...

    @abstractmethod
    async def ocr(self, image_bytes: bytes) -> OCRResult: ...

    # -- introspection ----------------------------------------------------
    @abstractmethod
    async def status(self) -> ModelRuntimeStatus: ...

    @abstractmethod
    def embedding_dimension(self, role: ModelRole = ModelRole.EMBEDDING) -> int: ...

    @abstractmethod
    def index_signature(self) -> dict[str, Any]:
        """Model identities baked into every index record for versioning."""

    @abstractmethod
    async def unload_role(self, role: ModelRole) -> bool:
        """Release one role's model and its VRAM; True if it had been loaded."""

    @abstractmethod
    async def unload_all(self) -> None: ...

    @abstractmethod
    def role_available(self, role: ModelRole) -> bool: ...

    @abstractmethod
    def degraded_reasons(self) -> list[str]: ...

    async def close(self) -> None:
        await self.unload_all()


_gateway: ModelGateway | None = None
_lock = asyncio.Lock()


async def get_gateway(settings: Settings | None = None) -> ModelGateway:
    global _gateway
    if _gateway is not None:
        return _gateway
    async with _lock:
        if _gateway is None:
            from .runtime_manager import ModelRuntimeManager

            manager = ModelRuntimeManager(settings or get_settings())
            await manager.initialise()
            _gateway = manager
    return _gateway


async def reset_gateway() -> None:
    global _gateway
    async with _lock:
        if _gateway is not None:
            await _gateway.close()
        _gateway = None
