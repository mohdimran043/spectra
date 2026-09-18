"""SPECTRA AI Core - the model gateway and runtime manager.

Importing this package pulls in **no** optional runtime: torch, llama.cpp,
sentence-transformers, faster-whisper, paddle and tesseract are all imported
lazily, inside the provider that needs them.

    from spectra_ai_core import ChatMessage, get_gateway

    gateway = await get_gateway()
    result = await gateway.embed_texts(["hello"])
"""

from __future__ import annotations

from .gateway import ModelGateway, get_gateway, reset_gateway
from .gpu import detect_gpu, gpu_memory_snapshot, is_oom_error
from .interfaces import (
    BaseProvider,
    ChatMessage,
    EmbeddingProvider,
    EmbeddingResult,
    GenerationResult,
    LLMProvider,
    OCRLine,
    OCRProvider,
    OCRResult,
    RerankerProvider,
    RerankResult,
    SpeechProvider,
    TranscriptionResult,
    TranscriptSegment,
    VisionDescription,
    VisionProvider,
)
from .phase import (
    ExecutionPhase,
    PhaseViolation,
    current_phase,
    ingestion_phase,
    query_phase,
)
from .registry import ModelRegistry, ProfileSpec, RoleSpec, get_registry
from .runtime_manager import ModelRuntimeManager

__all__ = [
    "query_phase",
    "ingestion_phase",
    "current_phase",
    "PhaseViolation",
    "ExecutionPhase",
    "BaseProvider",
    "ChatMessage",
    "EmbeddingProvider",
    "EmbeddingResult",
    "GenerationResult",
    "LLMProvider",
    "ModelGateway",
    "ModelRegistry",
    "ModelRuntimeManager",
    "OCRLine",
    "OCRProvider",
    "OCRResult",
    "ProfileSpec",
    "RerankResult",
    "RerankerProvider",
    "RoleSpec",
    "SpeechProvider",
    "TranscriptSegment",
    "TranscriptionResult",
    "VisionDescription",
    "VisionProvider",
    "detect_gpu",
    "get_gateway",
    "get_registry",
    "gpu_memory_snapshot",
    "is_oom_error",
    "reset_gateway",
]
