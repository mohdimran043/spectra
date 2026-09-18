<div align="center">

# SPECTRA

**Hypothesis-Driven Multimodal Enterprise Investigation Agent**

*Search → Understand → Investigate → Correlate → Challenge → Verify → Explain → Navigate*

</div>

---

## What SPECTRA is

SPECTRA is an agentic enterprise investigation platform. Given a question, it autonomously
investigates across **documents, images, audio, video, structured databases and configurable
external sources**. It resolves entities across modalities, generates and tests **competing
hypotheses**, retrieves supporting *and disconfirming* evidence, detects contradictions,
reconstructs timelines, maintains an evidence graph, verifies its conclusions, exposes full
provenance, and links every discovered entity to the corresponding enterprise application record.

It runs end to end on a single **RTX 4090 (24 GB)**, and is architected to scale to TB-scale corpora
and billions of rows without a rewrite.

## Why it is different

Most "multimodal RAG" systems retrieve, concatenate and generate. SPECTRA is built around four ideas
that retrieval systems do not have:

**1. Hypotheses, not answers.** For an investigation question it generates competing explanations and
scores each against the evidence — with an explicit lifecycle
(`OPEN → SUPPORTED / WEAK / CONTRADICTED / DISPROVED / INSUFFICIENT`).

**2. It tries to prove itself wrong.** The Disproof Agent is mandatory. For the leading hypothesis it
asks *"what evidence would refute this?"* and actively goes looking. A support-only system finds
three documents that agree with its first guess and reports 95% confidence. This one goes hunting for
the document that disagrees.

**3. Contradictions are explained, never hidden.** When the database says APPROVED and a document
says REJECTED, SPECTRA surfaces the conflict and adjudicates it using version status, recency,
source reliability and specificity — showing its reasoning.

**4. It can say "I don't know."** Evidence sufficiency is computed from weight, count, independent
sources, **diversity** and a contradiction penalty. Below threshold, SPECTRA abstains and says what
is missing. Abstention is a measured outcome in the benchmark suite, not an error path.

Plus one engineering idea that makes the rest possible: **ingestion and search are strictly
separated**. Every expensive operation — OCR, ASR, vision, embedding, scene detection — happens once,
at ingestion. Search reads indexes. No loop over videos at query time, ever.

## Architecture at a glance

```
INGESTION (offline, once)                      SEARCH (online, per query)
─────────────────────────                      ──────────────────────────
Source → Connector/Upload                      Query / image upload
  → extraction → normalisation                   → understanding
  → OCR / ASR / vision                           → SPECTRA BRAIN
  → chunking / scene segmentation                   ├ plan + hypotheses
  → entity extraction                               ├ select tools + sources
  → embeddings                                      ├ retrieve evidence
  → vector + lexical indexes                        ├ entity resolution
  → evidence graph                                  ├ evidence graph
                                                    ├ support + DISPROOF search
                                                    ├ contradiction check
                                                    ├ verify
                                                    └ confidence decision
                                                 → answer + evidence + provenance
                                                 → enterprise application links
```

Seven independently replaceable subsystems: `INGESTION · SEARCH · AGENT · MODELS · GRAPH ·
APPLICATION · UI`. Full detail in [docs/architecture.md](docs/architecture.md).

## Quick start

```bash
git clone <this repo> && cd spectra
cp .env.example .env

make install       # python venv + node deps
make up            # start the stack
make seed-demo     # generate and ingest the synthetic enterprise dataset
make demo          # run the guided scenarios
```

Open **http://localhost:3000** — the investigation console.
Open **http://localhost:3001** — the mock enterprise application SPECTRA links into.
API docs at **http://localhost:8000/docs**.

### Without Docker

```bash
./scripts/bootstrap.sh                                   # venv + deps + schema
.venv/bin/spectra serve                                  # API on :8000
.venv/bin/python -m spectra_worker                       # ingestion worker
cd apps/frontend && npm run dev                          # console on :3000
cd apps/mock-enterprise && npm run dev                   # enterprise app on :3001
```

It runs with **zero infrastructure** in this mode: SQLite, an in-process vector store, a real BM25
index in SQLite, a SQLite property graph, filesystem objects and an in-process cache. Flip any store
to Qdrant / OpenSearch / Neo4j / S3 / Redis / PostgreSQL with one `.env` line each.

## Requirements

| | Minimum | Recommended |
|---|---|---|
| OS | Linux / macOS | Ubuntu 22.04+ |
| Python | 3.10 | 3.12 |
| Node | 18.17 | 20 |
| RAM | 16 GB | 32 GB+ |
| Disk | 20 GB | 100 GB+ (models + media) |
| GPU | none (CPU fallback) | RTX 4090 24 GB + NVIDIA Container Toolkit for Docker |
| Tools | ffmpeg | ffmpeg, tesseract/PaddleOCR |

## Models

Nothing in the application names a model. Roles map to ordered candidates in
`packages/config/spectra_config/resources/models.yaml`, and the runtime manager picks the first that
is reachable and fits the VRAM budget. Change the hardware and the selection changes by itself:
on a GPU-less host every role falls back to CPU or the deterministic tier and says so; on the 4090
the cuda-only candidates qualify and Whisper moves from `base` to `large-v3` without a config edit.

<!-- BEGIN:model-table -->
Measured on **NVIDIA GeForce RTX 4090**, driver 580.178.04 · profile `rtx4090` · 21 GB usable.
Reproduce with `.venv/bin/python scripts/model_benchmark.py`.

| Role | Model | Runtime | Device | VRAM | Cold load | Warm call | Workload | Pipeline |
|---|---|---|---|---|---|---|---|---|
| **Deep brain** | `qwen3:30b-a3b` | ollama | cuda | 18.6 GB | 8.2 s | **5.27 s** | ~300 output tokens | query |
| **Fast brain** | `qwen3:8b` | ollama | cuda | 6.3 GB | 2.2 s | **438 ms** | ~60 output tokens | query |
| **Vision** | `qwen2.5vl:7b` | ollama | cuda | 7.8 GB | 2.6 s | **988 ms** | 1 image caption | ingest |
| **Text embedding** | `BAAI/bge-m3` | transformers | cuda | 2.3 GB | 8.6 s | **6 ms** | 1 short query | both |
| **Multimodal embedding** | `sentence-transformers/clip-ViT-B-32` | transformers | cuda | 0.7 GB | 8.4 s | **9 ms** | 1 image | ingest |
| **Reranker** | `BAAI/bge-reranker-v2-m3` | transformers | cuda | 2.3 GB | 5.3 s | **8 ms** | 4 pairs | query |
| **Speech (ASR)** | `large-v3` | faster_whisper | cuda | 4.4 GB | 3.2 s | **322 ms** | 3s audio | ingest |
| **OCR** | `PP-OCRv4` | rapidocr | cpu | CPU | 0.6 s | **258 ms** | 1 screenshot | ingest |

*Cold load* is first use, including any download already cached. *Warm call* is the median of three runs after warm-up.

The declared VRAM totals **42.5 GB** against a **21 GB usable** budget, which is why model residency is scheduled rather than assumed: roles are loaded on demand, evicted least-recently-used, and at most one heavyweight model is cuda-resident at a time. Watch it happen on the `/models` page during a deep investigation.

Roles marked `ingest` run **only** on the ingestion path and are refused at query time — see [Two pipelines](docs/architecture.md#2-two-pipelines-deliberately-separated).
<!-- END:model-table -->

### What that costs in practice

Per-model latency matters less than what a user waits for. Measured on the same 4090 against a
small corpus (a 13-page PDF plus a screenshot, 14 chunks, 5 entities):

| Operation | Time | Notes |
|---|---|---|
| Ingest a 13-page PDF | 8.8 s | extract → chunk → entities → embed → index, once per document |
| Ingest a screenshot | 13.6 s | OCR + vision caption + CLIP embedding, once per image |
| **Search (uncached)** | **92 ms** | full five-stage pipeline incl. cross-encoder rerank (median of 7 distinct queries, 90–93 ms) |
| **Search (cache hit)** | **2 ms** | same query, same role, same index version |
| **Fast-mode investigation** | **49 ms** | identifier lookup, 4 tool calls, no deep brain |
| Deep-mode investigation | 67 s | 3 iterations, 12 tool calls, 8 hypotheses, disproof + verification |

The shape is the point. Ingestion is seconds *per object, once*. Search is ~92 ms and does not grow
with corpus size, because it reads indexes rather than objects. A deep investigation costs a minute
because it is doing a minute of work — a dozen tool calls, competing hypotheses, a disconfirming
search and a verification pass — not because retrieval is slow.

### Without a GPU

The same code runs CPU-only; the registry simply selects different candidates and says so. Measured
on this host before the GPU was available:

| | CPU | RTX 4090 |
|---|---|---|
| Fast brain (~60 tokens) | 6.7 s | 438 ms |
| Deep brain (~300 tokens) | 22.3 s | 5.27 s |
| Speech model selected | `base` | `large-v3` |
| Reranker selected | MiniLM-L6 | bge-reranker-v2-m3 |

Nothing is configured to make that switch: `large-v3` and the bge reranker are declared
`device: cuda` in the registry, so they simply become eligible when a GPU appears. With no
generative runtime at all, synthesis falls back to the **extractive** deterministic tier and every
answer is flagged `degraded` with the reason.


Downloads:

```bash
make model-health        # what is reachable, what was selected, and why
ollama pull qwen3:8b     # if using the ollama runtime
ollama pull qwen2.5vl:7b
```

Supported runtimes: `llama_cpp · vllm · ollama · openai-compatible · transformers`, plus a
**deterministic** tier that provides real hashed-ngram embeddings, real IDF reranking and *extractive*
synthesis when nothing else is available — always flagged `degraded` with a reason.
**SPECTRA degrades into telling you less. It never degrades into making things up.**

## Example queries

```
Find transaction TX82931                                       → fast, database, <1s
Find documents about authentication failures                   → BM25 + dense + rerank
Find where the engineer discusses the authentication problem    → video + timestamp
Find architecture diagrams showing three database nodes         → text → image
Which customers mentioned in the engineering meeting had
  more than five failed payments?                               → video → entities → SQL
The sources disagree about whether the incident was approved.
  Investigate.                                                  → contradiction radar
Investigate why this transaction failed and show me the
  supporting evidence.                                          → full investigation
```

## Commands

| | |
|---|---|
| `make install` | venv + dependencies |
| `make up` / `make down` / `make logs` | stack lifecycle |
| `make seed-demo` | generate + ingest the demo dataset |
| `make ingest` / `make reindex` | ingest a path / rebuild indexes |
| `make test` / `make lint` / `make format` | quality gates |
| `make benchmark` | run the research evaluation |
| `make demo` | guided demo scenarios |
| `make gpu-check` / `make model-health` | hardware and model diagnostics |
| `make package-release` | cut a sealed offline deployment bundle |

Direct (non-Make) equivalents are in [docs/deployment.md](docs/deployment.md).

## Documentation

| | |
|---|---|
| [architecture.md](docs/architecture.md) | system design, layout, the two pipelines |
| [agent-design.md](docs/agent-design.md) | the Brain, hypotheses, disproof, verification, abstention |
| [search-architecture.md](docs/search-architecture.md) | staged retrieval and unified scoring |
| [model-strategy.md](docs/model-strategy.md) | model abstraction, registry, degradation |
| [4090-deployment.md](docs/4090-deployment.md) | 24 GB scheduling, OOM ladder, GPU dashboard |
| [data-model.md](docs/data-model.md) | ids, schemas, graph, index versioning |
| [api.md](docs/api.md) | the full HTTP contract |
| [evaluation.md](docs/evaluation.md) | benchmarks, baselines, metrics |
| [scaling.md](docs/scaling.md) | development → production topology |
| [security.md](docs/security.md) | controls, and what is *not* implemented |
| [deployment.md](docs/deployment.md) | dev stack and sealed offline operator bundles |
| [demo-guide.md](docs/demo-guide.md) | the scenarios and what to watch for |
| [progress.md](progress.md) | granular implementation status |

## Research positioning

This is not "a multimodal chatbot." The architecture is arranged so that ten capabilities can be
independently ablated and measured against five baselines over the same corpus — BM25, vector RAG,
multimodal RAG, agentic retrieval, and full SPECTRA. The `D → E` comparison isolates the contribution
of hypotheses, disconfirming search and verification from the contribution of merely being agentic.
See [docs/evaluation.md](docs/evaluation.md).

## Current limitations

Stated plainly:

- **The GPU is live, but only for host processes.** The RTX 4090 is usable (driver 580.178.04,
  `torch 2.8.0+cu128`, `detect_gpu()` reports `available=True`), and both brain roles run 100% on
  GPU. The **NVIDIA Container Toolkit is not installed**, so containers still cannot see the card:
  keep `GPU_ENABLED=0` for the Compose stack until it is. See
  [4090-deployment.md](docs/4090-deployment.md#host-yes-containers-not-yet).
- Synthesis is **generative** (Ollama: `qwen3:8b`, `qwen3:30b-a3b`, `qwen2.5vl:7b`). The
  deterministic extractive tier remains the last rung of the fallback ladder, not the default.
- Demo audio is synthetic with ground-truth transcripts (offline speech synthesis is out of scope);
  the real ASR pipeline runs on real audio.
- The embedded vector backend is brute-force cosine — correct and fast to ~10⁵ vectors; use Qdrant
  beyond that.
- Authentication is a role header shim, not an identity provider.

## Licence

Apache-2.0.
