# Model Strategy

## The problem

SPECTRA needs seven model capabilities — a deep reasoning brain, a fast router, a vision model, a
text embedder, a multimodal embedder, a reranker, and speech recognition, plus OCR — and it must run
on **one 24 GB card**. Loading them all simultaneously is not possible and never will be. The
architecture therefore treats model residency as a scheduling problem, not a configuration one.

## Capability, not model

Application code asks for a capability:

```python
await gateway.embed_texts(texts)
await gateway.generate(messages, role=ModelRole.DEEP_BRAIN)
await gateway.describe_image(image_bytes)
```

No agent, tool, pipeline or route names a model, a runtime or a device. The indirection means the
model set can change — or be swapped for remote endpoints — with zero changes above the gateway.

## The registry

`packages/config/resources/models.yaml` maps each **role** to an ordered list of **candidates**:

```yaml
deep_brain:
  candidates:
    - { runtime: ollama,        model: "qwen3:30b-a3b",                           vram_mb: 19000, device: cuda }
    - { runtime: vllm,          model: "Qwen/Qwen3-30B-A3B-Instruct-2507",        vram_mb: 21000, device: cuda }
    - { runtime: openai,        model: "${OPENAI_DEEP_MODEL:-gpt-4o}",            vram_mb: 0,     device: remote }
    - { runtime: llama_cpp,     model: "Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf", vram_mb: 19000, device: cuda }
    - { runtime: deterministic, model: "evidence-synthesis-v1",                   vram_mb: 0,     device: cpu }
  fallback_role: fast_brain
```

Selection at startup: the first candidate that is **reachable** and whose VRAM **fits the active
profile's budget**. Every rejection is recorded with its reason and shown in the Models dashboard.

## The default development set

| Role | Model | Why |
|---|---|---|
| Deep brain | Qwen3-30B-A3B-Instruct-2507 Q4_K_M | MoE: 30B capacity, ~3B active parameters, so it reasons well at a Q4 footprint that fits alongside nothing else |
| Fast brain | Qwen3-8B | Intent classification, rewriting, routing — cheap enough to call freely |
| Vision | Qwen3-VL-8B-Instruct Q4_K_M | Screenshots, diagrams, scanned pages, keyframes |
| Text embedding | BGE-M3 | Strong multilingual dense retrieval, 1024-d |
| Multimodal embedding | CLIP-family / Qwen3-VL-Embedding-2B | Shared text↔image space |
| Reranker | BGE-reranker-v2-m3 | Cross-encoder precision on the top-K only |
| Speech | faster-whisper large-v3 | Word-level timestamps, ingestion-time only |
| OCR | PaddleOCR (PP-OCRv4) | With VLM verification when confidence is low |

## Runtime independence

`MODEL_RUNTIME` selects the serving engine, and providers exist for each:

```
llama_cpp · vllm · ollama · openai (any OpenAI-shaped endpoint) · transformers · deterministic
```

The `LLMProvider` / `VisionProvider` / `EmbeddingProvider` / `RerankerProvider` / `SpeechProvider` /
`OCRProvider` interfaces mean adding a new engine is one file, not a refactor.

## The deterministic tier — honest degradation

When no generative runtime is reachable, SPECTRA does not fake one. The deterministic tier provides:

- **Hashed-ngram embeddings** — a real feature-hashing vectoriser with sublinear tf and L2
  normalisation. Genuinely useful for retrieval, fully reproducible, zero dependencies.
- **IDF-weighted lexical reranking** — real scoring, not a stub.
- **Extractive synthesis** — the answer is *assembled from retrieved evidence spans*, never
  generated. It cannot hallucinate because it does not write new sentences.

Every response from this tier sets `degraded: true` with a specific reason, surfaced in the API and
the UI. The product promise is: *SPECTRA tells you less when it knows less. It never invents.*

## Fallback ladder

```
requested role
  └─ next candidate (smaller quant / CPU device)
       └─ fallback_role   (deep_brain → fast_brain)
            └─ deterministic tier
```

Each step is logged as a `ModelEvent` and reflected in `degraded_reasons`.

## Index versioning

Every chunk is stamped with the model identities that produced it:

```
index_version · embedding_model · embedding_dimension · parser_version · vision_model · speech_model · ocr_engine
```

Changing an embedding model does not corrupt the live index — a new index version is written
alongside, and `make reindex` migrates. Cache keys include the embedding identity, so nothing stale
survives the switch.
