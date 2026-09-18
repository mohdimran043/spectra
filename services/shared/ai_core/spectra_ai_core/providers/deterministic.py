"""The deterministic tier: the honest last resort.

Nothing here pretends to be a language model.  Every provider is a real,
reproducible algorithm that degrades a capability rather than faking it, and
every result carries ``degraded=True`` with a reason the UI can show a user.
"""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from spectra_config.logging import get_logger

from ..interfaces import (
    ChatMessage,
    EmbeddingProvider,
    EmbeddingResult,
    GenerationResult,
    LLMProvider,
    OCRProvider,
    OCRResult,
    RerankerProvider,
    RerankResult,
    SpeechProvider,
    TranscriptionResult,
    VisionDescription,
    VisionProvider,
)
from ..textops import (
    NUMBER_PATTERN,
    find_identifiers,
    hash_vector,
    idf_weights,
    split_sentences,
    tokenize,
    weighted_overlap,
)
from .imaging import image_stats

log = get_logger(__name__)

RUNTIME_NAME = "deterministic"
AVAILABLE_REASON = "deterministic fallback"
DEFAULT_DIMENSION = 512

GENERATIVE_DEGRADED_REASON = "no generative runtime available; extractive synthesis"
EMBED_DEGRADED_REASON = "no embedding model available; hashed character-ngram vectoriser"
RERANK_DEGRADED_REASON = "no cross-encoder available; IDF-weighted lexical overlap"
SPEECH_DEGRADED_REASON = "no speech recognition runtime available; audio was not transcribed"
OCR_DEGRADED_REASON = "no OCR engine available; image text was not extracted"
VISION_DEGRADED_REASON = "no vision model available; caption derived from OCR text and image statistics"
MM_EMBED_DEGRADED_REASON = "no multimodal model available; images described by measured statistics"

# Extractive synthesis tuning.
MAX_EXCERPTS = 5
MIN_EXCERPT_SCORE = 0.02
MAX_ARRAY_ITEMS = 5
CONTEXT_MARKERS = ("context:", "evidence:", "documents:", "sources:", "retrieved:", "facts:", "records:")
QUESTION_MARKERS = ("question:", "query:", "task:", "instruction:", "request:", "ask:")
CONTEXT_TAG = re.compile(r"<context>(.*?)</context>", re.DOTALL | re.IGNORECASE)
BULLET_PATTERN = re.compile(r"^\s*(?:[-*•]|\[[^\]]+\]|\d+[.)])\s+")

HEADER_LINE = "EXTRACTIVE SYNTHESIS - no generative model is loaded."
QUESTION_LINE = "Question: {question}"
EXCERPT_HEADER = "Supporting excerpts copied verbatim from the supplied context, best match first:"
EXCERPT_LINE = "  {index}. {text}"
NO_CONTEXT_LINE = "No context was supplied with this prompt, so there is nothing to extract."
NO_MATCH_LINE = "No excerpt in the supplied context matches the question."
FOOTER_LINE = "Nothing above is paraphrased, inferred or invented; install a generative runtime for synthesis."

# Field names whose value should be an identifier, not a whole sentence.
ID_FIELD_HINTS = ("id", "identifier", "ref", "reference", "code", "number", "no")

# Every token the template itself can emit: its fixed prose, plus the ordinals
# produced by EXCERPT_LINE's list numbering.  Exposed so callers and tests can
# separate template output from content quoted out of the caller's context.
TEMPLATE_TOKENS: frozenset[str] = frozenset(
    tokenize(
        " ".join(
            (HEADER_LINE, QUESTION_LINE, EXCERPT_HEADER, NO_CONTEXT_LINE, NO_MATCH_LINE, FOOTER_LINE)
        )
    )
) | {str(index) for index in range(1, MAX_EXCERPTS + 1)}


class _DeterministicProvider:
    """Always reachable, by construction."""

    runtime_name = RUNTIME_NAME

    async def available(self) -> tuple[bool, str]:
        return True, AVAILABLE_REASON


class HashedNgramEmbedding(_DeterministicProvider, EmbeddingProvider):
    """Feature-hashed word + character-ngram vectoriser.

    Sublinear term frequency, signed hashing and L2 normalisation give vectors
    that behave sensibly under cosine similarity: exact identifiers and shared
    vocabulary score high, unrelated text scores near zero.  It is not semantic,
    but it is real retrieval and it is byte-for-byte reproducible.
    """

    def __init__(self, model: str = "hashed-ngram-v1", device: str = "cpu", **options: Any) -> None:
        super().__init__(model, device, **options)
        self.dimension = int(options.get("dimension") or DEFAULT_DIMENSION)

    async def embed_texts(self, texts: Sequence[str], *, is_query: bool = False) -> EmbeddingResult:
        started = time.perf_counter()
        vectors = [hash_vector(text, self.dimension) for text in texts]
        return EmbeddingResult(
            vectors=vectors,
            model=self.model,
            runtime=RUNTIME_NAME,
            dimension=self.dimension,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            degraded=True,
            degraded_reason=EMBED_DEGRADED_REASON,
        )


class VisualDescriptorEmbedding(HashedNgramEmbedding):
    """Deterministic stand-in for a multimodal space.

    Images are reduced to a measured textual descriptor (geometry, tone,
    dominant colours) and hashed with the *same* vectoriser as text, so the two
    modalities genuinely share one space - a query like "dark wide screenshot"
    has real purchase.  No visual semantics are claimed.
    """

    async def embed_images(self, images: Sequence[bytes]) -> EmbeddingResult:
        started = time.perf_counter()
        descriptors = [describe_image_statistically(payload) for payload in images]
        vectors = [hash_vector(text, self.dimension) for text in descriptors]
        return EmbeddingResult(
            vectors=vectors,
            model=self.model,
            runtime=RUNTIME_NAME,
            dimension=self.dimension,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            degraded=True,
            degraded_reason=MM_EMBED_DEGRADED_REASON,
        )


def describe_image_statistically(image_bytes: bytes) -> str:
    """A sentence built purely from measurements - never from recognition."""
    stats = image_stats(image_bytes)
    if "error" in stats:
        return f"undecodable image {stats['mime']} of {stats['byte_size']} bytes"
    colours = " ".join(stats["dominant_colours"])
    return (
        f"{stats['mime']} image {stats['width']}x{stats['height']} pixels "
        f"mode {stats['mode']} aspect {stats['aspect_ratio']} "
        f"{stats['tone']} brightness {stats['mean_brightness']} colours {colours}"
    )


class LexicalOverlapReranker(_DeterministicProvider, RerankerProvider):
    """IDF-weighted Jaccard overlap with an exact-identifier bonus.

    The IDF statistics come from the candidate set itself, which is exactly the
    corpus available at rerank time.
    """

    def __init__(self, model: str = "lexical-overlap-v1", device: str = "cpu", **options: Any) -> None:
        super().__init__(model, device, **options)

    async def rerank(self, query: str, documents: Sequence[str]) -> RerankResult:
        started = time.perf_counter()
        tokenised = [tokenize(document) for document in documents]
        idf = idf_weights(tokenised)
        query_tokens = tokenize(query)
        scores = [round(weighted_overlap(query_tokens, tokens, idf), 6) for tokens in tokenised]
        return RerankResult(
            scores=scores,
            model=self.model,
            runtime=RUNTIME_NAME,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            degraded=True,
            degraded_reason=RERANK_DEGRADED_REASON,
        )


# -- extractive synthesis --------------------------------------------------


def _strip_marker(line: str, markers: Sequence[str]) -> str | None:
    lowered = line.strip().lower()
    for marker in markers:
        if lowered.startswith(marker):
            return line.strip()[len(marker) :].strip()
    return None


def _split_units(block: str) -> list[str]:
    """Bullet/evidence lines stay whole; prose is split into sentences."""
    units: list[str] = []
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if BULLET_PATTERN.match(stripped):
            units.append(stripped)
        else:
            units.extend(split_sentences(stripped))
    return units


def split_prompt(messages: Sequence[ChatMessage]) -> tuple[str, list[str]]:
    """Separate the question from the structured context block in a prompt."""
    joined = "\n".join(message.content for message in messages)
    tagged = CONTEXT_TAG.findall(joined)
    question, context_lines = _scan_lines(joined)
    if tagged:
        context_lines = [line for block in tagged for line in _split_units(block)]
    if not question:
        question = _fallback_question(messages)
    return question, [unit for unit in context_lines if unit]


def _scan_lines(joined: str) -> tuple[str, list[str]]:
    question = ""
    context_block: list[str] = []
    in_context = False
    for line in CONTEXT_TAG.sub(" ", joined).splitlines():
        marked_question = _strip_marker(line, QUESTION_MARKERS)
        if marked_question is not None:
            question, in_context = marked_question or question, False
            continue
        marked_context = _strip_marker(line, CONTEXT_MARKERS)
        if marked_context is not None:
            in_context = True
            context_block.append(marked_context)
            continue
        if in_context:
            context_block.append(line)
    return question, _split_units("\n".join(context_block))


def _fallback_question(messages: Sequence[ChatMessage]) -> str:
    """With no explicit marker, the final user turn is the question."""
    for message in reversed(messages):
        if message.role == "user" and message.content.strip():
            lines = [line.strip() for line in message.content.splitlines() if line.strip()]
            return next((line for line in reversed(lines) if line.endswith("?")), lines[-1] if lines else "")
    return ""


def rank_excerpts(question: str, units: Sequence[str]) -> list[tuple[str, float]]:
    """Rank context units against the question with the same lexical maths as the reranker."""
    if not units:
        return []
    tokenised = [tokenize(unit) for unit in units]
    idf = idf_weights(tokenised)
    query_tokens = tokenize(question)
    scored = [
        (unit, weighted_overlap(query_tokens, tokens, idf)) for unit, tokens in zip(units, tokenised, strict=True)
    ]
    ranked = sorted(scored, key=lambda item: item[1], reverse=True)
    return [item for item in ranked[:MAX_EXCERPTS] if item[1] >= MIN_EXCERPT_SCORE]


class ExtractiveLLM(_DeterministicProvider, LLMProvider):
    """Assembles an answer by *quoting* the prompt's context, never by writing prose.

    The only generated language is the fixed template above; every substantive
    line is copied verbatim from the caller's own context block.  When a JSON
    schema is supplied the same excerpts are slotted into a schema-valid object,
    so downstream parsers keep working without a single invented fact.
    """

    def __init__(self, model: str = "evidence-synthesis-v1", device: str = "cpu", **options: Any) -> None:
        super().__init__(model, device, **options)

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
        started = time.perf_counter()
        question, units = split_prompt(messages)
        excerpts = rank_excerpts(question, units)
        structured = build_from_schema(json_schema, question, excerpts) if json_schema else None
        text = _render(question, units, excerpts) if structured is None else _dump(structured)
        return GenerationResult(
            text=text,
            model=self.model,
            runtime=RUNTIME_NAME,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            finish_reason="stop",
            structured=structured,
            degraded=True,
            degraded_reason=GENERATIVE_DEGRADED_REASON,
        )


def _dump(structured: dict[str, Any]) -> str:
    import json

    return json.dumps(structured, ensure_ascii=False, indent=2)


def _render(question: str, units: Sequence[str], excerpts: Sequence[tuple[str, float]]) -> str:
    lines = [HEADER_LINE, QUESTION_LINE.format(question=question or "(none supplied)")]
    if not units:
        lines.append(NO_CONTEXT_LINE)
    elif not excerpts:
        lines.append(NO_MATCH_LINE)
    else:
        lines.append(EXCERPT_HEADER)
        lines.extend(
            EXCERPT_LINE.format(index=index, text=text)
            for index, (text, _score) in enumerate(excerpts, start=1)
        )
    lines.append(FOOTER_LINE)
    return "\n".join(lines)


def build_from_schema(
    schema: dict[str, Any] | None, question: str, excerpts: Sequence[tuple[str, float]]
) -> dict[str, Any]:
    """Build a schema-valid object whose every value is drawn from the context."""
    texts = [text for text, _score in excerpts]
    node = _fill_node(schema or {}, "", texts, question)
    return node if isinstance(node, dict) else {"value": node}


def _fill_node(schema: dict[str, Any], name: str, texts: Sequence[str], question: str) -> Any:
    if "enum" in schema:
        return _best_enum(schema["enum"], texts, name)
    node_type = schema.get("type") or ("object" if "properties" in schema else "string")
    if node_type == "object":
        properties: dict[str, Any] = schema.get("properties") or {}
        return {key: _fill_node(sub or {}, key, texts, question) for key, sub in properties.items()}
    if node_type == "array":
        return _fill_array(schema, name, texts, question)
    if node_type in {"integer", "number"}:
        return _first_number(texts, name, integral=node_type == "integer")
    if node_type == "boolean":
        return False
    if node_type == "null":
        return None
    return _best_identifier(texts, name) if _is_id_field(name) else _best_text(texts, name)


def _fill_array(schema: dict[str, Any], name: str, texts: Sequence[str], question: str) -> list[Any]:
    items: dict[str, Any] = schema.get("items") or {"type": "string"}
    limit = min(int(schema.get("maxItems") or MAX_ARRAY_ITEMS), MAX_ARRAY_ITEMS, len(texts) or 0)
    if items.get("type") == "string" and "enum" not in items:
        return list(texts[:limit])
    return [_fill_node(items, name, [text], question) for text in texts[:limit]]


def _best_text(texts: Sequence[str], name: str) -> str:
    """The context excerpt that best matches this field's own name."""
    if not texts:
        return ""
    ranked = rank_excerpts(name.replace("_", " "), texts)
    return ranked[0][0] if ranked else texts[0]


def _is_id_field(name: str) -> bool:
    return any(token in ID_FIELD_HINTS for token in tokenize(name))


def _best_identifier(texts: Sequence[str], name: str) -> str:
    """Quote just the identifier out of the best excerpt - still verbatim, better shaped."""
    excerpt = _best_text(texts, name)
    found = find_identifiers(excerpt)
    return found[0] if found else excerpt


def _best_enum(values: Sequence[Any], texts: Sequence[str], name: str) -> Any:
    if not values:
        return None
    joined_tokens = tokenize(" ".join(texts))
    scored = [(value, len(set(tokenize(str(value))) & set(joined_tokens))) for value in values]
    best = max(scored, key=lambda item: item[1])
    return best[0] if best[1] else values[0]


def _first_number(texts: Sequence[str], name: str, *, integral: bool) -> float | int:
    """Only attribute a number to a field when the context actually mentions that field.

    Otherwise a ``confidence`` property would happily absorb the ``1`` out of an
    ``[E1]`` label and report certainty nobody claimed.
    """
    zero: float | int = 0 if integral else 0.0
    wanted = set(tokenize(name.replace("_", " ")))
    for text in texts:
        if wanted and not wanted & set(tokenize(text)):
            continue
        match = NUMBER_PATTERN.search(text)
        if match is not None:
            value = float(match.group())
            return int(value) if integral else value
    return zero


# -- degraded media providers ---------------------------------------------


class NoOpSpeech(_DeterministicProvider, SpeechProvider):
    """Reports the audio's real duration and transcribes nothing, loudly."""

    def __init__(self, model: str = "no-asr-v1", device: str = "cpu", **options: Any) -> None:
        super().__init__(model, device, **options)

    async def transcribe(
        self, audio_path: str, *, language: str | None = None, diarize: bool = False
    ) -> TranscriptionResult:
        return TranscriptionResult(
            segments=[],
            language=language or "unknown",
            duration=_wav_duration(audio_path),
            model=self.model,
            runtime=RUNTIME_NAME,
            degraded=True,
            degraded_reason=SPEECH_DEGRADED_REASON,
        )


def _wav_duration(audio_path: str) -> float:
    """Measured from the RIFF header when the file is a WAV; 0.0 otherwise."""
    import contextlib
    import wave

    with contextlib.suppress(Exception):
        with wave.open(audio_path, "rb") as handle:
            rate = handle.getframerate()
            return round(handle.getnframes() / rate, 4) if rate else 0.0
    return 0.0


class NoOpOCR(_DeterministicProvider, OCRProvider):
    """Extracts no text and says so, rather than returning a plausible blank page."""

    def __init__(self, model: str = "no-ocr-v1", device: str = "cpu", **options: Any) -> None:
        super().__init__(model, device, **options)

    async def read(self, image_bytes: bytes) -> OCRResult:
        return OCRResult(
            lines=[],
            engine=f"{RUNTIME_NAME}:{self.model}",
            degraded=True,
            degraded_reason=OCR_DEGRADED_REASON,
        )


OcrResolver = Callable[[], Awaitable[OCRProvider | None]]


class OCRCaptionVision(_DeterministicProvider, VisionProvider):
    """Caption = whatever OCR could read + measured image statistics.

    No object detection is attempted and ``objects`` stays empty, because
    guessing at image content is exactly the failure this tier exists to avoid.
    """

    def __init__(self, model: str = "ocr-caption-v1", device: str = "cpu", **options: Any) -> None:
        super().__init__(model, device, **options)
        self._ocr_resolver: OcrResolver | None = options.get("ocr_resolver")

    async def _read_text(self, image_bytes: bytes) -> str:
        if self._ocr_resolver is None:
            return ""
        try:
            provider = await self._ocr_resolver()
            return (await provider.read(image_bytes)).text if provider is not None else ""
        except Exception as exc:
            log.warning("deterministic.vision_ocr_failed", error=str(exc))
            return ""

    async def describe(
        self, image_bytes: bytes, prompt: str = "", *, max_tokens: int = 512
    ) -> VisionDescription:
        started = time.perf_counter()
        detected = await self._read_text(image_bytes)
        descriptor = describe_image_statistically(image_bytes)
        suffix = f" Text read from the image: {detected!r}." if detected else " No text could be read."
        return VisionDescription(
            caption=f"{descriptor}.{suffix}",
            detected_text=detected,
            objects=[],
            model=self.model,
            runtime=RUNTIME_NAME,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            degraded=True,
            degraded_reason=VISION_DEGRADED_REASON,
        )
