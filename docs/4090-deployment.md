# Running SPECTRA on one RTX 4090 (24 GB)

## The constraint

Seven model capabilities, 24 GB, one card. The deep brain alone is ~19 GB at Q4. Vision is ~8 GB.
Embeddings, reranker and Whisper are another ~9 GB combined. Nothing about "load everything" works.

SPECTRA therefore schedules model residency the way an OS schedules memory.

## MODEL_PROFILE=rtx4090

```yaml
rtx4090:
  vram_budget_mb: 22000          # 24 GB card, ~2 GB reserved for the display server and fragmentation
  allow_concurrent_gpu_models: false
  prefer_device: cuda
```

The budget is **22000 MB**. This document writes it as 22 GB; the generated README table renders the
same value in binary units as *21 GB usable* (22000 MB ≈ 21.5 GiB). One number, two conventions.

`allow_concurrent_gpu_models: false` is the important line. At most one heavyweight CUDA-resident
role at a time; everything else is evicted or runs on CPU.

## Sequential execution

```
Brain model  ──unload──►  Vision model  ──unload──►  Embedding  ──unload──►  Reranker
```

A single `asyncio.Lock` guards GPU residency. Before loading a model that would exceed the remaining
budget, the manager evicts least-recently-used GPU-resident models, emitting a `ModelEvent` for each
so the Models dashboard shows the swap happening live.

Small models (embeddings ~2.4 GB, reranker ~2.4 GB) can stay resident; the manager only evicts what
it must.

## Lazy loading and idle eviction

Models load on first use, not at startup — otherwise startup would be a five-minute VRAM thrash.
A background task evicts anything unused for `MODEL_IDLE_EVICT_SECONDS` (default 300), so a long
document-only session does not keep the vision model pinned.

## The OOM recovery ladder

An out-of-memory error is a routine event here, not a crash:

```
1. reduce context / max_tokens and retry
2. unload other GPU-resident models and retry
3. move to the next candidate (smaller quantisation, or CPU device)
4. fall back to the role's fallback_role  (deep_brain → fast_brain)
5. fall back to the deterministic tier
```

Each rung is logged as a `ModelEvent`, surfaced in `degraded_reasons`, and shown in the UI.
**An OOM never propagates as an unhandled error.**

## What runs where

| Role | Device | VRAM | Notes |
|---|---|---|---|
| Deep brain | CUDA | ~19 GB | Evicts everything else while resident |
| Fast brain | CUDA | ~6.5 GB | Can co-reside with the small models |
| Vision | CUDA | ~8 GB | Ingestion-time and visual verification only |
| Text embedding | CUDA or CPU | ~2.4 GB | CPU is viable; this is the first thing to demote |
| Multimodal embedding | CUDA or CPU | ~0.7 GB | |
| Reranker | CUDA or CPU | ~2.4 GB | Top-K only, so CPU latency is acceptable |
| Speech | CUDA or CPU | ~4.5 GB | Ingestion only — never on the query path |
| OCR | CPU | 0 | PaddleOCR CPU is fast enough for ingestion |

Because ASR and OCR are ingestion-only, they never compete with generation during a query. That is a
scheduling consequence of the ingestion/search split, not a coincidence.

## GPU dashboard

`GET /api/models` and the `/models` page expose:

```
RTX 4090
VRAM              18.9 / 24 GB
Current model     Qwen3-30B-A3B Q4
GPU utilisation   —
Model queue       —
Active agent      —
```

plus per-role state, runtime, device, VRAM, call count, average latency, error count, and a live feed
of load/unload events. Watching models swap while searching is the clearest single
demonstration of how the constraint is being managed.

## Verifying GPU availability

```bash
make gpu-check
```

### GPU status on this host

The driver/library version mismatch that previously made the card unusable is **resolved**. The
4090 path described above is now the operative path, not an aspiration. `make gpu-check` reports:

```
==> NVIDIA driver
  [ok]   NVIDIA GeForce RTX 4090
  [ok]   driver 580.178.04, VRAM 335 MiB used of 24564 MiB

==> CUDA runtime
  [ok]   driver supports CUDA 13.0 (nvcc not installed; not needed for prebuilt wheels)

==> Docker GPU runtime
  [warn] the NVIDIA Container Toolkit is not registered with Docker

==> PyTorch
  [ok]   torch 2.8.0+cu128 sees NVIDIA GeForce RTX 4090 (23.5 GiB)

==> Summary
  GPU looks usable. Recommended: MODEL_PROFILE=rtx4090, GPU_ENABLED=1
```

`detect_gpu()` returns `available=True`, `driver_version='580.178.04'`, `total_mb=24564`,
`detail='nvml'`. The runtime manager therefore schedules against the real 22 GB budget, roles select
their CUDA candidates, and answers are no longer flagged degraded for want of a GPU.

Measured on this host, both brain roles are fully GPU-resident — `ollama ps` reports
`100% GPU` for each:

| Role | Model | Resident (`ollama ps`) | Decode rate | Cold load |
|---|---|---|---|---|
| fast_brain | `qwen3:8b` | 6.5 GB | ~135 tok/s | ~5.6 s |
| deep_brain | `qwen3:30b-a3b` (MoE) | 20 GB | ~159 tok/s | ~9.6–12.6 s |

*Decode rate* is `eval_count / eval_duration` from the Ollama response — pure token generation,
excluding prompt eval and load. The end-to-end **warm call** figures in the
[README model table](../README.md#models) are the more useful operational number, because they
include prompt evaluation: 443 ms for ~60 fast-brain tokens, 4.84 s for ~300 deep-brain tokens.
Both describe the same runs; they simply measure different spans.

The deep brain is a 30B MoE with ~3B active parameters, which is why it decodes no slower than the
8B dense model despite holding far more weights. Note the gap between *declared* VRAM (18.6 GB in
the registry) and *resident* VRAM (~20 GB once the KV cache for a 4096-token context is allocated) —
budget accounting has to assume the larger figure. At ~20 GB resident the deep brain leaves roughly
2 GB of the 22 GB budget, which is exactly why `allow_concurrent_gpu_models: false` and the eviction
ladder are load-bearing rather than defensive decoration: loading the deep brain evicts the fast
brain, and `ollama ps` shows it happening.

The full eight-role measurement — every role on CUDA except OCR, with Whisper promoted from `base`
to `large-v3` by the profile alone — is generated into the README from
`scripts/model_benchmark.py`. Declared VRAM across all eight roles totals **42.5 GB** against a
22 GB budget, which is the whole reason this document exists.

### Host yes, containers not yet

One gap remains, and it is host configuration rather than code: the **NVIDIA Container Toolkit is
not installed**, so `docker info` lists only the `runc` runtime.

| Execution path | GPU |
|---|---|
| Host process (`uvicorn spectra_api.main:app`, `pytest`, `scripts/*.sh`, the Ollama daemon) | yes |
| Compose stack (`make up`, `deploy.sh`) | no — keep `GPU_ENABLED=0` |

Passing the GPU overlay before installing the toolkit fails at container create time with:

```
could not select device driver "nvidia" with capabilities: [[gpu]]
```

To close the gap:

```bash
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

docker info | grep -i runtimes     # must now list "nvidia"
make gpu-check                     # the Docker GPU runtime section turns [ok]
```

Then set `GPU_ENABLED=1` in `.env` and start with `make up GPU=1` (developer), or let `deploy.sh`
add the overlay itself (operator).

## Running without a GPU at all

```bash
MODEL_PROFILE=cpu make up
```

Embeddings, reranking and OCR run on CPU; generation falls back to whatever runtime is reachable, or
to the extractive deterministic tier. Every response is flagged degraded with the reason.

## Using remote inference instead

```bash
MODEL_RUNTIME=openai
OPENAI_BASE_URL=https://your-endpoint/v1
OPENAI_API_KEY=...
```

VRAM accounting is bypassed for remote candidates. Retrieval, entity resolution, the graph and the
evidence machinery are unchanged — only where the tokens are produced differs.
