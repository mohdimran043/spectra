"""The Model Runtime Manager: lazy loading, sequential GPU scheduling, graceful decay.

One object owns every model decision on the box:

* selection - the first candidate that is reachable *and* fits the VRAM budget
* scheduling - a single lock, LRU eviction, idle eviction
* recovery - an OOM ladder that ends in the deterministic tier rather than a stack trace
* reporting - per-role metrics and a ring buffer of events for the UI

Nothing it returns is ever silently wrong: a result produced by a lesser tier
carries ``degraded=True`` and a reason a human can act on.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from spectra_config import Settings, get_settings
from spectra_config.logging import get_logger
from spectra_schemas import (
    GPUStatus,
    ModelCandidate,
    ModelInfo,
    ModelRole,
    ModelRuntimeStatus,
    ModelState,
)

from . import events as ev
from .events import EventLog
from .gateway import ModelGateway
from .gpu import detect_gpu, is_oom_error
from .interfaces import (
    BaseProvider,
    ChatMessage,
    EmbeddingResult,
    GenerationResult,
    OCRProvider,
    OCRResult,
    RerankResult,
    TranscriptionResult,
    VisionDescription,
)
from .phase import guard
from .providers import UnsupportedCandidateError, build_provider
from .registry import ModelRegistry, ProfileSpec, RoleSpec
from .scheduler import GpuScheduler
from .selection import (
    CUDA,
    DETERMINISTIC_RUNTIME,
    PROBE_CONCURRENCY,
    Selection,
    SelectionContext,
    resolve_device,
    select_for_role,
)

log = get_logger(__name__)

MIN_MAX_TOKENS = 128
VISION_MAX_TOKENS = 512
OOM_SCALE = 0.5
EMBED_BATCH_SIZE = 32
MIN_BATCH_SIZE = 1
RETRY_BACKOFF_SECONDS = 0.25
MIN_IDLE_CHECK_SECONDS = 5.0
MAX_IDLE_CHECK_SECONDS = 60.0
IDLE_CHECK_DIVISOR = 4
MAX_REPORTED_REJECTIONS = 3
NO_GPU_DEGRADED_REASON = "profile prefers cuda but no GPU is usable"

# Errors that mean "the caller gave us bad input" - never degraded away.
INPUT_ERRORS: tuple[type[BaseException], ...] = (FileNotFoundError, ValueError, TypeError)

Invoke = Callable[[BaseProvider, float], Awaitable[Any]]


class RoleUnavailableError(RuntimeError):
    """No candidate for this role can run on this machine."""


class VramExhaustedError(RuntimeError):
    """The role cannot be admitted to the GPU even after eviction."""


@dataclass(frozen=True)
class LadderStep:
    """One rung of the OOM recovery ladder."""

    event: str
    scale: float = 1.0
    evict_peers: bool = False
    advance_candidate: bool = False
    deterministic: bool = False


# (1) smaller request, (2) free the card, (3) a smaller/CPU candidate, (4) deterministic.
OOM_LADDER: tuple[LadderStep, ...] = (
    LadderStep(ev.EVENT_OOM_REDUCED, scale=OOM_SCALE),
    LadderStep(ev.EVENT_OOM_EVICTED_PEERS, scale=OOM_SCALE, evict_peers=True),
    LadderStep(ev.EVENT_OOM_NEXT_CANDIDATE, scale=OOM_SCALE, advance_candidate=True),
    LadderStep(ev.EVENT_OOM_DETERMINISTIC, deterministic=True),
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ModelRuntimeManager(ModelGateway):
    """The concrete :class:`ModelGateway` for a single-GPU (or GPU-less) box."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._registry: ModelRegistry | None = None
        self._specs: dict[ModelRole, RoleSpec] = {}
        self._gpu = GPUStatus(detail="not probed yet")
        self._scheduler: GpuScheduler | None = None
        self._events = EventLog()
        self._info: dict[ModelRole, ModelInfo] = {}
        self._providers: dict[ModelRole, BaseProvider] = {}
        self._deterministic: dict[ModelRole, BaseProvider] = {}
        self._inflight: Counter[ModelRole] = Counter()
        self._active_role: ModelRole | None = None
        self._idle_task: asyncio.Task[None] | None = None
        self._init_lock = asyncio.Lock()
        self._initialised = False

    # -- lifecycle --------------------------------------------------------
    async def initialise(self) -> None:
        """Probe hardware, choose an implementation per role, start idle eviction."""
        async with self._init_lock:
            if self._initialised:
                return
            registry = ModelRegistry.load()
            profile = registry.profile(self.settings.model_profile.value)
            self._registry = registry
            self._specs = {spec.role: spec for spec in registry.roles()}
            self._gpu = await asyncio.to_thread(detect_gpu, self.settings)
            budget = min(profile.vram_budget_mb, self.settings.gpu_vram_budget_mb) if self._gpu.available else 0
            self._scheduler = GpuScheduler(profile, budget)
            await self._select_all(profile)
            self._idle_task = asyncio.create_task(self._idle_loop())
            self._initialised = True
            log.info(
                "runtime.initialised",
                profile=profile.name,
                gpu=self._gpu.available,
                budget_mb=budget,
                degraded=[info.role.value for info in self._info.values() if info.degraded],
            )

    async def _select_all(self, profile: ProfileSpec) -> None:
        context = SelectionContext(self.settings, profile, self._gpu, ocr_resolver=self._resolve_ocr)
        gate = asyncio.Semaphore(PROBE_CONCURRENCY)
        specs = tuple(self._specs.values())
        selections = await asyncio.gather(*(select_for_role(spec, context, gate) for spec in specs))
        for spec, selection in zip(specs, selections, strict=True):
            self._apply_selection(spec, selection)

    def _apply_selection(self, spec: RoleSpec, selection: Selection) -> None:
        candidate = selection.candidate
        on_gpu = selection.device == CUDA and candidate is not None
        info = ModelInfo(
            role=spec.role,
            enabled=spec.enabled,
            purpose=spec.purpose,
            state=ModelState.REGISTERED if selection.provider else ModelState.UNAVAILABLE,
            active_runtime=candidate.runtime if candidate else None,
            active_model=candidate.model if candidate else None,
            device=selection.device if selection.provider else None,
            vram_mb=candidate.vram_mb if on_gpu and candidate else 0,
            dimension=(candidate.dimension if candidate else None) or spec.dimension,
            candidates=list(selection.candidates),
            degraded=selection.provider is None or selection.is_degraded,
            degraded_reason=_degraded_reason(selection),
        )
        self._info[spec.role] = info
        if selection.provider is not None:
            self._providers[spec.role] = selection.provider
            self._events.record(
                spec.role, ev.EVENT_SELECTED, f"{info.active_runtime}/{info.active_model} on {info.device}",
                info.vram_mb,
            )
            return
        self._events.record(spec.role, ev.EVENT_UNAVAILABLE, selection.reason)

    async def unload_role(self, role: ModelRole) -> bool:
        """Release one role's model, freeing its VRAM.  Returns whether it was loaded.

        Used by the Models dashboard to hand memory back on demand, and by the
        scheduler when a heavier role needs the space.
        """
        provider = self._providers.get(role)
        if provider is None or not provider.is_loaded:
            return False
        await self._evict(role, ev.EVENT_UNLOADED)
        return True

    async def unload_all(self) -> None:
        """Stop idle eviction and release every loaded model."""
        task, self._idle_task = self._idle_task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        for role in list(self._providers):
            await self._evict(role, ev.EVENT_UNLOADED)
        for provider in self._deterministic.values():
            await _unload_quietly(provider)
        self._deterministic.clear()

    # -- loading and eviction --------------------------------------------
    async def _provider_for(self, role: ModelRole) -> BaseProvider:
        provider = self._providers.get(role)
        if provider is None:
            info = self._info.get(role)
            raise RoleUnavailableError(f"{role.value}: {info.degraded_reason if info else 'not initialised'}")
        await self._ensure_loaded(role, provider)
        return provider

    async def _ensure_loaded(self, role: ModelRole, provider: BaseProvider) -> None:
        scheduler = self._require_scheduler()
        info = self._info[role]
        if provider.is_loaded:
            scheduler.touch(role)
            return
        if info.device != CUDA or info.vram_mb <= 0:
            await self._load(role, provider)
            return
        async with scheduler.waiting():
            if provider.is_loaded:
                scheduler.touch(role)
                return
            plan = scheduler.plan(role, info.vram_mb, self._busy_roles())
            if not plan.is_admissible:
                raise VramExhaustedError(f"{role.value} cannot be admitted: {plan.refusal}")
            for victim in plan.evict:
                await self._evict(victim, ev.EVENT_EVICTED_FOR_SPACE)
            await self._load(role, provider)
            scheduler.admit(role, info.vram_mb)

    async def _load(self, role: ModelRole, provider: BaseProvider) -> None:
        info = self._info[role]
        self._update(role, state=ModelState.LOADING)
        try:
            await asyncio.wait_for(provider.load(), timeout=self.settings.model_load_timeout_seconds)
        except Exception as exc:
            self._update(role, state=ModelState.ERROR, last_error=f"load failed: {exc}")
            raise
        moment = _now()
        self._update(
            role,
            state=ModelState.LOADED,
            loaded_at=moment,
            last_used_at=moment,
            load_count=info.load_count + 1,
            last_error=None,
        )
        self._events.record(
            role, ev.EVENT_LOADED, f"{info.active_runtime}/{info.active_model} on {info.device}", info.vram_mb
        )

    async def _evict(self, role: ModelRole, event: str) -> None:
        provider = self._providers.get(role)
        if provider is None or not provider.is_loaded:
            return
        info = self._info[role]
        self._update(role, state=ModelState.UNLOADING)
        await _unload_quietly(provider)
        self._require_scheduler().release(role)
        self._update(role, state=ModelState.REGISTERED, loaded_at=None, unload_count=info.unload_count + 1)
        self._events.record(role, event, f"{info.active_runtime}/{info.active_model}", info.vram_mb)

    async def _idle_loop(self) -> None:
        interval = min(
            MAX_IDLE_CHECK_SECONDS,
            max(MIN_IDLE_CHECK_SECONDS, self.settings.model_idle_evict_seconds / IDLE_CHECK_DIVISOR),
        )
        try:
            while True:
                await asyncio.sleep(interval)
                await self._evict_idle()
        except asyncio.CancelledError:
            return

    async def _evict_idle(self) -> None:
        cutoff = _now() - timedelta(seconds=self.settings.model_idle_evict_seconds)
        busy = self._busy_roles()
        for role, provider in list(self._providers.items()):
            info = self._info[role]
            last_used = info.last_used_at or info.loaded_at
            if not provider.is_loaded or role in busy or last_used is None or last_used > cutoff:
                continue
            await self._evict(role, ev.EVENT_EVICTED_IDLE)

    # -- execution --------------------------------------------------------
    async def _execute(
        self, role: ModelRole, operation: str, invoke: Invoke, *, allow_deterministic: bool = True
    ) -> Any:
        """Run one capability call, with retries, then the OOM ladder."""
        try:
            provider = await self._provider_for(role)
        except (RoleUnavailableError, VramExhaustedError):
            if not allow_deterministic:
                raise
            return await self._deterministic_attempt(role, operation, invoke)
        try:
            return await self._attempt(role, operation, provider, invoke, 1.0)
        except Exception as exc:
            if not is_oom_error(exc):
                raise
            self._events.record(role, ev.EVENT_OOM, f"{operation}: {exc}")
        return await self._walk_oom_ladder(role, operation, invoke, allow_deterministic)

    async def _attempt(
        self, role: ModelRole, operation: str, provider: BaseProvider, invoke: Invoke, scale: float
    ) -> Any:
        attempts = max(1, self.settings.model_max_retries + 1)
        timeout = self.settings.model_call_timeout_seconds
        for attempt in range(1, attempts + 1):
            self._begin(role)
            started = asyncio.get_running_loop().time()
            try:
                result = await asyncio.wait_for(invoke(provider, scale), timeout=timeout)
            except Exception as exc:
                self._record_error(role, operation, exc, started)
                if is_oom_error(exc) or attempt >= attempts:
                    raise
                self._events.record(role, ev.EVENT_RETRY, f"{operation} attempt {attempt}/{attempts}: {exc}")
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempt)
            else:
                self._record_success(role, started)
                return result
            finally:
                self._end(role)
        raise RuntimeError(f"{role.value}: {operation} exhausted {attempts} attempts")  # pragma: no cover

    async def _walk_oom_ladder(
        self, role: ModelRole, operation: str, invoke: Invoke, allow_deterministic: bool
    ) -> Any:
        scale = 1.0
        failure: Exception = RuntimeError(f"{role.value}: {operation} ran out of memory")
        for step in OOM_LADDER:
            if step.deterministic and not allow_deterministic:
                break
            scale *= step.scale
            provider = await self._prepare_step(role, operation, step)
            if provider is None:
                continue
            self._events.record(role, step.event, f"{operation} retry at scale {scale:.2f}")
            try:
                return await self._attempt(role, operation, provider, invoke, scale)
            except Exception as exc:
                failure = exc
                self._events.record(role, ev.EVENT_CALL_FAILED, f"{operation} after {step.event}: {exc}")
        raise failure

    async def _prepare_step(self, role: ModelRole, operation: str, step: LadderStep) -> BaseProvider | None:
        """Apply a ladder rung's side effect and return the provider to retry with."""
        try:
            if step.deterministic:
                return await self._load_deterministic(role)
            if step.evict_peers:
                await self._evict_gpu_peers(role)
            if step.advance_candidate:
                return await self._advance_candidate(role)
            return await self._provider_for(role)
        except Exception as exc:
            self._events.record(role, ev.EVENT_CALL_FAILED, f"{operation} preparing {step.event}: {exc}")
            return None

    async def _evict_gpu_peers(self, role: ModelRole) -> None:
        scheduler = self._require_scheduler()
        busy = self._busy_roles()
        async with scheduler.waiting():
            for other in scheduler.resident_roles():
                if other != role and other not in busy:
                    await self._evict(other, ev.EVENT_EVICTED_FOR_SPACE)

    async def _advance_candidate(self, role: ModelRole) -> BaseProvider | None:
        """Fall forward to the next usable candidate - typically smaller, or CPU."""
        info = self._info[role]
        remaining = _candidates_after(info)
        for candidate in remaining:
            provider = await self._try_candidate(role, candidate)
            if provider is not None:
                return provider
        return None

    async def _try_candidate(self, role: ModelRole, candidate: ModelCandidate) -> BaseProvider | None:
        scheduler = self._require_scheduler()
        device = resolve_device(candidate.device, scheduler.profile, self._gpu.available)
        if device is None:
            return None
        try:
            provider = build_provider(
                candidate=candidate,
                role=role,
                settings=self.settings,
                device=device,
                dimension=self._specs[role].dimension,
                ocr_resolver=self._resolve_ocr,
            )
            ok, reason = await provider.available()
        except (UnsupportedCandidateError, RuntimeError, OSError) as exc:
            log.info("runtime.candidate_probe_failed", role=role.value, model=candidate.model, error=str(exc))
            return None
        if not ok:
            log.info("runtime.candidate_rejected", role=role.value, model=candidate.model, reason=reason)
            return None
        await self._adopt(role, candidate, provider, device)
        return provider

    async def _adopt(
        self, role: ModelRole, candidate: ModelCandidate, provider: BaseProvider, device: str
    ) -> None:
        await self._evict(role, ev.EVENT_UNLOADED)
        self._providers[role] = provider
        self._update(
            role,
            state=ModelState.REGISTERED,
            active_runtime=candidate.runtime,
            active_model=candidate.model,
            device=device,
            vram_mb=candidate.vram_mb if device == CUDA else 0,
            dimension=candidate.dimension or self._specs[role].dimension,
            degraded=candidate.runtime == DETERMINISTIC_RUNTIME,
            degraded_reason=f"fell forward to {candidate.runtime}/{candidate.model} after a memory failure",
        )
        await self._ensure_loaded(role, provider)

    # -- deterministic tier ----------------------------------------------
    def _deterministic_candidate(self, role: ModelRole) -> ModelCandidate | None:
        spec = self._specs.get(role)
        if spec is None:
            return None
        return next((c for c in spec.candidates if c.runtime == DETERMINISTIC_RUNTIME), None)

    async def _load_deterministic(self, role: ModelRole) -> BaseProvider:
        existing = self._deterministic.get(role)
        if existing is not None:
            return existing
        candidate = self._deterministic_candidate(role)
        if candidate is None:
            raise RoleUnavailableError(f"{role.value}: models.yaml declares no deterministic candidate")
        provider = build_provider(
            candidate=candidate,
            role=role,
            settings=self.settings,
            device="cpu",
            dimension=self._specs[role].dimension,
            ocr_resolver=self._resolve_ocr,
        )
        await provider.load()
        self._deterministic[role] = provider
        return provider

    async def _deterministic_attempt(self, role: ModelRole, operation: str, invoke: Invoke) -> Any:
        provider = await self._load_deterministic(role)
        self._events.record(role, ev.EVENT_DEGRADED, f"{operation} served by the deterministic tier")
        return await self._attempt(role, operation, provider, invoke, 1.0)

    async def _execute_or_degrade(self, role: ModelRole, operation: str, invoke: Invoke) -> Any:
        """Non-generative capabilities never fail an investigation; they degrade."""
        try:
            return await self._execute(role, operation, invoke)
        except INPUT_ERRORS:
            raise
        except Exception as exc:
            self._events.record(role, ev.EVENT_DEGRADED, f"{operation} failed ({exc}); deterministic tier")
            return await self._deterministic_attempt(role, operation, invoke)

    async def _resolve_ocr(self) -> OCRProvider | None:
        provider = self._providers.get(ModelRole.OCR)
        if provider is None or not isinstance(provider, OCRProvider):
            return None
        await self._ensure_loaded(ModelRole.OCR, provider)
        return provider

    # -- capabilities: generation ----------------------------------------
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
        await self.initialise()
        chain = self._role_chain(role)
        failures: list[str] = []

        async def invoke(provider: BaseProvider, scale: float) -> GenerationResult:
            return await provider.generate(
                messages,
                max_tokens=max(MIN_MAX_TOKENS, int(max_tokens * scale)),
                temperature=temperature,
                json_schema=json_schema,
                tools=tools,
            )

        for index, link in enumerate(chain):
            is_last = index == len(chain) - 1
            try:
                result = await self._execute(link, "generate", invoke, allow_deterministic=is_last)
            except Exception as exc:
                failures.append(f"{link.value}: {exc}")
                self._events.record(link, ev.EVENT_FALLBACK_ROLE, str(exc))
                continue
            return _mark_degraded(result, link is not role, failures)
        return _mark_degraded(await self._deterministic_attempt(role, "generate", invoke), True, failures)

    def _role_chain(self, role: ModelRole) -> tuple[ModelRole, ...]:
        """``deep_brain -> fast_brain`` comes from ``fallback_role`` in models.yaml."""
        chain: list[ModelRole] = [role]
        seen = {role}
        current = self._specs.get(role)
        while current is not None and current.fallback_role and current.fallback_role not in seen:
            chain.append(current.fallback_role)
            seen.add(current.fallback_role)
            current = self._specs.get(current.fallback_role)
        return tuple(chain)

    # -- capabilities: embeddings ----------------------------------------
    async def embed_texts(self, texts: Sequence[str], *, is_query: bool = False) -> EmbeddingResult:
        result = await self._embed_texts(ModelRole.EMBEDDING, texts, is_query=is_query)
        return self._checked_dimension(ModelRole.EMBEDDING, result)

    async def embed_text_for_image_space(self, texts: Sequence[str]) -> EmbeddingResult:
        result = await self._embed_texts(ModelRole.MM_EMBEDDING, texts, is_query=True)
        return self._checked_dimension(ModelRole.MM_EMBEDDING, result)

    def _checked_dimension(self, role: ModelRole, result: EmbeddingResult) -> EmbeddingResult:
        """Flag a fallback that silently changed the embedding dimension.

        An index built at 1024 dimensions cannot be queried with a 512-dimension
        vector: the store rejects it and dense retrieval quietly disappears from
        the results.  A degraded model must therefore be *loud* about a
        dimension change, so the caller can report reduced recall rather than
        returning lexical-only results that look complete.
        """
        expected = self.embedding_dimension(role)
        if not result.vectors or result.dimension == expected:
            return result
        reason = (
            f"{role.value} produced {result.dimension}-dimension vectors but the index was built at "
            f"{expected}; dense retrieval for this query is unavailable"
        )
        log.error(
            "embedding.dimension_mismatch",
            role=role.value,
            produced=result.dimension,
            expected=expected,
            model=result.model,
        )
        return replace(
            result,
            degraded=True,
            degraded_reason="; ".join(filter(None, (result.degraded_reason, reason))),
        )

    async def _embed_texts(
        self, role: ModelRole, texts: Sequence[str], *, is_query: bool
    ) -> EmbeddingResult:
        await self.initialise()
        payload = list(texts)
        if not payload:
            return EmbeddingResult(vectors=[], model="", runtime="", dimension=self.embedding_dimension(role))

        async def invoke(provider: BaseProvider, scale: float) -> EmbeddingResult:
            return await _chunked_embed(
                lambda batch: provider.embed_texts(batch, is_query=is_query), payload, scale
            )

        return await self._execute_or_degrade(role, "embed_texts", invoke)

    async def embed_images(self, images: Sequence[bytes]) -> EmbeddingResult:
        guard("embed_images")
        await self.initialise()
        payload = list(images)
        role = ModelRole.MM_EMBEDDING
        if not payload:
            return EmbeddingResult(vectors=[], model="", runtime="", dimension=self.embedding_dimension(role))

        async def invoke(provider: BaseProvider, scale: float) -> EmbeddingResult:
            return await _chunked_embed(provider.embed_images, payload, scale)

        return await self._execute_or_degrade(role, "embed_images", invoke)

    # -- capabilities: rerank / vision / speech / ocr ---------------------
    async def rerank(self, query: str, documents: Sequence[str]) -> RerankResult:
        await self.initialise()
        payload = list(documents)
        if not payload:
            return RerankResult(scores=[], model="", runtime="")

        async def invoke(provider: BaseProvider, _scale: float) -> RerankResult:
            return await provider.rerank(query, payload)

        return await self._execute_or_degrade(ModelRole.RERANKER, "rerank", invoke)

    async def describe_image(self, image_bytes: bytes, prompt: str = "") -> VisionDescription:
        guard("describe_image")
        await self.initialise()

        async def invoke(provider: BaseProvider, scale: float) -> VisionDescription:
            return await provider.describe(
                image_bytes, prompt, max_tokens=max(MIN_MAX_TOKENS, int(VISION_MAX_TOKENS * scale))
            )

        return await self._execute_or_degrade(ModelRole.VISION, "describe_image", invoke)

    async def transcribe(
        self, audio_path: str, *, language: str | None = None, diarize: bool = False
    ) -> TranscriptionResult:
        guard("transcribe")
        await self.initialise()

        async def invoke(provider: BaseProvider, _scale: float) -> TranscriptionResult:
            return await provider.transcribe(audio_path, language=language, diarize=diarize)

        return await self._execute_or_degrade(ModelRole.SPEECH, "transcribe", invoke)

    async def ocr(self, image_bytes: bytes) -> OCRResult:
        guard("ocr")
        await self.initialise()

        async def invoke(provider: BaseProvider, _scale: float) -> OCRResult:
            return await provider.read(image_bytes)

        return await self._execute_or_degrade(ModelRole.OCR, "ocr", invoke)

    # -- introspection ----------------------------------------------------
    async def status(self) -> ModelRuntimeStatus:
        await self.initialise()
        scheduler = self._require_scheduler()
        gpu = await asyncio.to_thread(detect_gpu, self.settings) if self._gpu.available else self._gpu
        reasons = self.degraded_reasons()
        return ModelRuntimeStatus(
            profile=scheduler.profile.name,
            gpu=gpu.model_copy(update={"budget_mb": float(scheduler.budget_mb)}),
            models=[self._info[role] for role in ModelRole if role in self._info],
            resident_roles=scheduler.resident_roles(),
            queue_depth=scheduler.queue_depth,
            active_role=self._active_role,
            recent_events=self._events.recent(),
            degraded=bool(reasons),
            degraded_reasons=reasons,
        )

    def embedding_dimension(self, role: ModelRole = ModelRole.EMBEDDING) -> int:
        info = self._info.get(role)
        provider = self._providers.get(role)
        return int(getattr(provider, "dimension", 0) or (info.dimension if info else 0) or 0)

    def index_signature(self) -> dict[str, Any]:
        """Stamped onto every index record so a model change invalidates stale vectors."""
        scheduler = self._scheduler
        signature: dict[str, Any] = {
            "profile": scheduler.profile.name if scheduler else self.settings.model_profile.value,
            "embedding_dimension": self.embedding_dimension(ModelRole.EMBEDDING),
            "mm_embedding_dimension": self.embedding_dimension(ModelRole.MM_EMBEDDING),
            "degraded": bool(self.degraded_reasons()),
        }
        for role in ModelRole:
            info = self._info.get(role)
            signature[role.value] = f"{info.active_runtime}/{info.active_model}" if info and info.active_model else None
        return signature

    def role_available(self, role: ModelRole) -> bool:
        return self._providers.get(role) is not None

    def degraded_reasons(self) -> list[str]:
        reasons = [
            f"{info.role.value}: {info.degraded_reason}"
            for info in self._info.values()
            if info.degraded and info.degraded_reason
        ]
        scheduler = self._scheduler
        if scheduler and scheduler.profile.prefer_device == CUDA and not self._gpu.available:
            reasons.insert(0, f"gpu: {NO_GPU_DEGRADED_REASON} ({self._gpu.detail})")
        return reasons

    # -- bookkeeping ------------------------------------------------------
    def _require_scheduler(self) -> GpuScheduler:
        if self._scheduler is None:
            raise RuntimeError("ModelRuntimeManager.initialise() has not been awaited")
        return self._scheduler

    def _busy_roles(self) -> frozenset[ModelRole]:
        return frozenset(role for role, count in self._inflight.items() if count > 0)

    def _update(self, role: ModelRole, **changes: Any) -> ModelInfo:
        """Replace a role's ModelInfo immutably and return the new snapshot."""
        updated = self._info[role].model_copy(update=changes)
        self._info[role] = updated
        return updated

    def _begin(self, role: ModelRole) -> None:
        self._inflight[role] += 1
        self._active_role = role

    def _end(self, role: ModelRole) -> None:
        self._inflight[role] = max(0, self._inflight[role] - 1)

    def _record_success(self, role: ModelRole, started: float) -> None:
        info = self._info[role]
        elapsed = (asyncio.get_running_loop().time() - started) * 1000.0
        self._update(
            role,
            call_count=info.call_count + 1,
            total_latency_ms=info.total_latency_ms + elapsed,
            last_used_at=_now(),
        )
        self._require_scheduler().touch(role)

    def _record_error(self, role: ModelRole, operation: str, exc: Exception, started: float) -> None:
        info = self._info[role]
        elapsed = (asyncio.get_running_loop().time() - started) * 1000.0
        self._update(
            role,
            call_count=info.call_count + 1,
            error_count=info.error_count + 1,
            total_latency_ms=info.total_latency_ms + elapsed,
            last_error=f"{operation}: {type(exc).__name__}: {exc}",
            last_used_at=_now(),
        )


# -- module helpers --------------------------------------------------------


async def _unload_quietly(provider: BaseProvider) -> None:
    try:
        await provider.unload()
    except Exception as exc:  # unload must never block the caller
        log.warning("runtime.unload_failed", provider=type(provider).__name__, error=str(exc))


def _candidates_after(info: ModelInfo) -> tuple[ModelCandidate, ...]:
    names = [candidate.model for candidate in info.candidates]
    start = names.index(info.active_model) + 1 if info.active_model in names else 0
    return tuple(info.candidates[start:])


def _degraded_reason(selection: Selection) -> str | None:
    if selection.provider is None:
        return selection.reason or "no usable candidate"
    if not selection.is_degraded:
        return None
    rejected = [
        f"{candidate.runtime}/{candidate.model}: {candidate.unavailable_reason}"
        for candidate in selection.candidates
        if candidate.available is False and candidate.unavailable_reason
    ]
    summary = "; ".join(rejected[:MAX_REPORTED_REJECTIONS]) or "no higher tier was reachable"
    return f"deterministic tier in use - {summary}"


def _mark_degraded(result: GenerationResult, used_fallback: bool, failures: Sequence[str]) -> GenerationResult:
    if not used_fallback and not failures:
        return result
    reason = result.degraded_reason or ("; ".join(failures) if failures else "served by a fallback role")
    return replace(result, degraded=True, degraded_reason=reason)


async def _chunked_embed(
    call: Callable[[Sequence[Any]], Awaitable[EmbeddingResult]], payload: Sequence[Any], scale: float
) -> EmbeddingResult:
    """Batch size shrinks with the OOM ladder's scale; results are concatenated."""
    size = max(MIN_BATCH_SIZE, int(EMBED_BATCH_SIZE * scale))
    if len(payload) <= size:
        return await call(payload)
    chunks = [payload[start : start + size] for start in range(0, len(payload), size)]
    results = [await call(chunk) for chunk in chunks]
    first = results[0]
    return replace(
        first,
        vectors=[vector for result in results for vector in result.vectors],
        latency_ms=sum(result.latency_ms for result in results),
        degraded=any(result.degraded for result in results),
    )
