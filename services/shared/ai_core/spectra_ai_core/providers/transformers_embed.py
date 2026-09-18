"""sentence-transformers providers: dense text, cross-encoder rerank, CLIP.

Models are constructed in a worker thread inside :meth:`load` - never at import
time - so a machine with no weights cached still imports this module fine.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from typing import Any

from spectra_config.logging import get_logger

from ..interfaces import (
    EmbeddingProvider,
    EmbeddingResult,
    RerankerProvider,
    RerankResult,
)
from .hf_assets import asset_status
from .imaging import open_image

log = get_logger(__name__)

RUNTIME_NAME = "transformers"
SENTENCE_TRANSFORMERS = "sentence_transformers"
TORCH = "torch"
QUERY_PROMPT_NAME = "query"
DEFAULT_DIMENSION = 512


def effective_device(requested: str) -> str:
    """Honour the profile, but never hand a dead CUDA device to torch."""
    if requested != "cuda":
        return "cpu" if requested in {"auto", "remote", ""} else requested
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception as exc:
        log.info("transformers.cuda_probe_failed", error=str(exc))
        return "cpu"


class _SentenceTransformerBase:
    """Shared availability, threaded load and device downgrade."""

    runtime_name = RUNTIME_NAME

    def __init__(self, model: str, device: str = "auto", **options: Any) -> None:
        super().__init__(model, device, **options)  # type: ignore[call-arg]
        self.dimension = int(options.get("dimension") or DEFAULT_DIMENSION)
        self._model: Any | None = None
        self._resolved_device = effective_device(device)

    @property
    def resolved_device(self) -> str:
        return self._resolved_device

    async def available(self) -> tuple[bool, str]:
        # asset_status may touch the network, so keep it off the event loop.
        return await asyncio.to_thread(asset_status, self.model, SENTENCE_TRANSFORMERS, TORCH)

    async def load(self) -> None:
        if self._model is not None:
            return
        ok, reason = await self.available()
        if not ok:
            raise RuntimeError(f"cannot load {self.model}: {reason}")
        self._resolved_device = effective_device(self.device)
        self._model = await asyncio.to_thread(self._construct)
        self._after_load()
        await super().load()  # type: ignore[misc]
        log.info(
            "transformers.loaded",
            model=self.model,
            device=self._resolved_device,
            dimension=self.dimension,
        )

    def _construct(self) -> Any:  # pragma: no cover - overridden
        raise NotImplementedError

    def _after_load(self) -> None:
        """Hook for subclasses that can report a true dimension post-load."""

    async def unload(self) -> None:
        self._model = None
        await asyncio.to_thread(_release_torch_cache)
        await super().unload()  # type: ignore[misc]

    async def _require(self) -> Any:
        await self.load()
        if self._model is None:  # pragma: no cover - load() raises first
            raise RuntimeError(f"{self.model} is not loaded")
        return self._model


def _release_torch_cache() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # noqa: S110 - cache release is best-effort
        pass


def _read_dimension(model: Any, fallback: int) -> int:
    """sentence-transformers renamed this accessor; support both spellings."""
    for name in ("get_embedding_dimension", "get_sentence_embedding_dimension"):
        accessor = getattr(model, name, None)
        if callable(accessor):
            value = accessor()
            if value:
                return int(value)
    return fallback


class SentenceTransformerEmbedding(_SentenceTransformerBase, EmbeddingProvider):
    """Dense text embeddings (bge-m3 and friends), L2-normalised for cosine search."""

    def _construct(self) -> Any:
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(self.model, device=self._resolved_device)

    def _after_load(self) -> None:
        self.dimension = _read_dimension(self._model, self.dimension)

    def _query_prompt(self) -> str | None:
        """Use the model's own declared query prompt when it has a non-empty one."""
        prompts = getattr(self._model, "prompts", None) or {}
        return QUERY_PROMPT_NAME if prompts.get(QUERY_PROMPT_NAME) else None

    async def embed_texts(self, texts: Sequence[str], *, is_query: bool = False) -> EmbeddingResult:
        model = await self._require()
        started = time.perf_counter()
        prompt_name = self._query_prompt() if is_query else None
        vectors = await asyncio.to_thread(
            lambda: model.encode(
                list(texts), normalize_embeddings=True, prompt_name=prompt_name, show_progress_bar=False
            ).tolist()
        )
        return EmbeddingResult(
            vectors=vectors,
            model=self.model,
            runtime=RUNTIME_NAME,
            dimension=self.dimension,
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )


class ClipMultimodalEmbedding(_SentenceTransformerBase, EmbeddingProvider):
    """CLIP: text and images embedded into one shared space, so either can query the other."""

    def _construct(self) -> Any:
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(self.model, device=self._resolved_device)

    def _after_load(self) -> None:
        self.dimension = _read_dimension(self._model, self.dimension)

    async def _encode(self, items: Sequence[Any], started: float) -> EmbeddingResult:
        model = await self._require()
        vectors = await asyncio.to_thread(
            lambda: model.encode(list(items), normalize_embeddings=True, show_progress_bar=False).tolist()
        )
        return EmbeddingResult(
            vectors=vectors,
            model=self.model,
            runtime=RUNTIME_NAME,
            dimension=self.dimension,
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )

    async def embed_texts(self, texts: Sequence[str], *, is_query: bool = False) -> EmbeddingResult:
        await self._require()
        return await self._encode(list(texts), time.perf_counter())

    async def embed_images(self, images: Sequence[bytes]) -> EmbeddingResult:
        await self._require()
        started = time.perf_counter()
        decoded = [open_image(payload).convert("RGB") for payload in images]
        return await self._encode(decoded, started)


class CrossEncoderReranker(_SentenceTransformerBase, RerankerProvider):
    """Cross-encoder relevance scoring of (query, document) pairs."""

    def _construct(self) -> Any:
        from sentence_transformers import CrossEncoder

        return CrossEncoder(self.model, device=self._resolved_device)

    async def rerank(self, query: str, documents: Sequence[str]) -> RerankResult:
        if not documents:
            return RerankResult(scores=[], model=self.model, runtime=RUNTIME_NAME)
        model = await self._require()
        started = time.perf_counter()
        pairs = [(query, document) for document in documents]
        scores = await asyncio.to_thread(
            lambda: [float(score) for score in model.predict(pairs, show_progress_bar=False)]
        )
        return RerankResult(
            scores=scores,
            model=self.model,
            runtime=RUNTIME_NAME,
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )
