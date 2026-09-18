"""Provider factory.

Every heavy or optional dependency is imported *inside* a builder, so importing
``spectra_ai_core`` works on a machine with none of the runtimes installed.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from spectra_config import Settings
from spectra_schemas import ModelCandidate, ModelRole

from ..interfaces import BaseProvider, OCRProvider

OcrResolver = Callable[[], Awaitable[OCRProvider | None]]

LLM_ROLES = frozenset({ModelRole.FAST_BRAIN, ModelRole.DEEP_BRAIN})
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"


class UnsupportedCandidateError(RuntimeError):
    """The registry pairs a runtime with a role that runtime cannot serve."""


def _reject(candidate: ModelCandidate, role: ModelRole) -> BaseProvider:
    raise UnsupportedCandidateError(
        f"runtime {candidate.runtime!r} cannot serve role {role.value!r} (model {candidate.model!r})"
    )


def _build_ollama(candidate: ModelCandidate, role: ModelRole, context: dict[str, Any]) -> BaseProvider:
    from .ollama import OllamaLLM, OllamaVision

    options = {
        "base_url": context["settings"].ollama_base_url,
        "timeout_seconds": context["timeout_seconds"],
    }
    if role in LLM_ROLES:
        return OllamaLLM(candidate.model, context["device"], **options)
    if role is ModelRole.VISION:
        return OllamaVision(candidate.model, context["device"], **options)
    return _reject(candidate, role)


def _openai_options(candidate: ModelCandidate, context: dict[str, Any]) -> dict[str, Any]:
    settings: Settings = context["settings"]
    is_vllm = candidate.runtime == "vllm"
    base_url = settings.vllm_base_url if is_vllm else (settings.openai_base_url or DEFAULT_OPENAI_BASE_URL)
    return {
        "base_url": base_url,
        "api_key": settings.openai_api_key,
        "runtime_label": candidate.runtime,
        "timeout_seconds": context["timeout_seconds"],
    }


def _build_openai_compatible(
    candidate: ModelCandidate, role: ModelRole, context: dict[str, Any]
) -> BaseProvider:
    from .openai_compatible import OpenAICompatibleLLM, OpenAICompatibleVision

    options = _openai_options(candidate, context)
    if role in LLM_ROLES:
        return OpenAICompatibleLLM(candidate.model, context["device"], **options)
    if role is ModelRole.VISION:
        return OpenAICompatibleVision(candidate.model, context["device"], **options)
    return _reject(candidate, role)


def _build_llama_cpp(candidate: ModelCandidate, role: ModelRole, context: dict[str, Any]) -> BaseProvider:
    from .llama_cpp import LlamaCppLLM, LlamaCppVision

    options = {"model_dir": context["settings"].model_dir}
    if role in LLM_ROLES:
        return LlamaCppLLM(candidate.model, context["device"], **options)
    if role is ModelRole.VISION:
        return LlamaCppVision(candidate.model, context["device"], **options)
    return _reject(candidate, role)


def _build_transformers(
    candidate: ModelCandidate, role: ModelRole, context: dict[str, Any]
) -> BaseProvider:
    from .transformers_embed import (
        ClipMultimodalEmbedding,
        CrossEncoderReranker,
        SentenceTransformerEmbedding,
    )

    options = {"dimension": context["dimension"]}
    if role is ModelRole.EMBEDDING:
        return SentenceTransformerEmbedding(candidate.model, context["device"], **options)
    if role is ModelRole.MM_EMBEDDING:
        return ClipMultimodalEmbedding(candidate.model, context["device"], **options)
    if role is ModelRole.RERANKER:
        return CrossEncoderReranker(candidate.model, context["device"], **options)
    return _reject(candidate, role)


def _build_whisper(candidate: ModelCandidate, role: ModelRole, context: dict[str, Any]) -> BaseProvider:
    from .whisper import FasterWhisperSpeech

    if role is not ModelRole.SPEECH:
        return _reject(candidate, role)
    return FasterWhisperSpeech(
        candidate.model, context["device"], compute_type=candidate.compute_type
    )


def _build_paddle(candidate: ModelCandidate, role: ModelRole, context: dict[str, Any]) -> BaseProvider:
    from .ocr import PaddleOCRProvider

    if role is not ModelRole.OCR:
        return _reject(candidate, role)
    return PaddleOCRProvider(candidate.model, context["device"])


def _build_rapidocr(candidate: ModelCandidate, role: ModelRole, context: dict[str, Any]) -> BaseProvider:
    from .rapidocr import RapidOCRProvider

    return RapidOCRProvider(candidate.model, candidate.device)


def _build_tesseract(candidate: ModelCandidate, role: ModelRole, context: dict[str, Any]) -> BaseProvider:
    from .ocr import TesseractOCRProvider

    if role is not ModelRole.OCR:
        return _reject(candidate, role)
    return TesseractOCRProvider(candidate.model, context["device"])


def _build_deterministic(
    candidate: ModelCandidate, role: ModelRole, context: dict[str, Any]
) -> BaseProvider:
    from .deterministic import (
        ExtractiveLLM,
        HashedNgramEmbedding,
        LexicalOverlapReranker,
        NoOpOCR,
        NoOpSpeech,
        OCRCaptionVision,
        VisualDescriptorEmbedding,
    )

    dimension = context["dimension"]
    builders: dict[ModelRole, Callable[[], BaseProvider]] = {
        ModelRole.FAST_BRAIN: lambda: ExtractiveLLM(candidate.model),
        ModelRole.DEEP_BRAIN: lambda: ExtractiveLLM(candidate.model),
        ModelRole.VISION: lambda: OCRCaptionVision(candidate.model, ocr_resolver=context.get("ocr_resolver")),
        ModelRole.EMBEDDING: lambda: HashedNgramEmbedding(candidate.model, dimension=dimension),
        ModelRole.MM_EMBEDDING: lambda: VisualDescriptorEmbedding(candidate.model, dimension=dimension),
        ModelRole.RERANKER: lambda: LexicalOverlapReranker(candidate.model),
        ModelRole.SPEECH: lambda: NoOpSpeech(candidate.model),
        ModelRole.OCR: lambda: NoOpOCR(candidate.model),
    }
    builder = builders.get(role)
    return builder() if builder else _reject(candidate, role)


BUILDERS: dict[str, Callable[[ModelCandidate, ModelRole, dict[str, Any]], BaseProvider]] = {
    "ollama": _build_ollama,
    "vllm": _build_openai_compatible,
    "openai": _build_openai_compatible,
    "llama_cpp": _build_llama_cpp,
    "transformers": _build_transformers,
    "faster_whisper": _build_whisper,
    "paddleocr": _build_paddle,
    "rapidocr": _build_rapidocr,
    "tesseract": _build_tesseract,
    "deterministic": _build_deterministic,
}


def build_provider(
    *,
    candidate: ModelCandidate,
    role: ModelRole,
    settings: Settings,
    device: str,
    dimension: int | None = None,
    ocr_resolver: OcrResolver | None = None,
) -> BaseProvider:
    """Construct (but never load) the provider for one registry candidate."""
    builder = BUILDERS.get(candidate.runtime)
    if builder is None:
        raise UnsupportedCandidateError(f"unknown runtime {candidate.runtime!r} for role {role.value!r}")
    context: dict[str, Any] = {
        "settings": settings,
        "device": device,
        "dimension": candidate.dimension or dimension,
        "timeout_seconds": float(settings.model_call_timeout_seconds),
        "ocr_resolver": ocr_resolver,
    }
    return builder(candidate, role, context)


__all__ = ["BUILDERS", "OcrResolver", "UnsupportedCandidateError", "build_provider"]
