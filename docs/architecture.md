# SPECTRA — Architecture

SPECTRA is a multimodal retrieval-augmented generation (RAG) system. It ingests documents,
images, audio, video, and structured databases; builds searchable indexes; and answers natural-language
queries over the indexed content with retrieval-grounded answers. Every result carries full provenance
to its source, and no assertion reaches a user without a citation to a retrieved passage.

It is designed to run completely on a single RTX 4090 (24 GB) and to scale to TB-scale corpora and
billions of rows without a rewrite.

---

## 1. The organising principle

Seven things are independently replaceable. A change to one must not force a rewrite of another:

```
INGESTION   SEARCH   ANSWER   MODELS   STORAGE   APPLICATION   UI
```

Every boundary between them is a typed contract in `packages/schemas`, not a function call into
another subsystem's internals. That is why the repository is laid out the way it is.

---

## 2. Two pipelines, deliberately separated

### Pipeline A — ingestion / indexing (expensive, offline, once per object)

```
Source
  └─ Connector / Upload
       └─ Content extraction        (PDF/DOCX/PPTX/XLSX/CSV/HTML/MD/JSON, EXIF, ffprobe)
            └─ Normalisation
                 └─ Metadata extraction
                      └─ OCR / ASR / vision       (only here — never at query time)
                           └─ Entity extraction
                                └─ Chunking / scene segmentation
                                     └─ Embeddings
                                          └─ Search indexes (vector + lexical)
```

### Pipeline B — search / answer (cheap, online, per query)

```
User query / image upload
  └─ Query understanding
       └─ FIVE-STAGE RETRIEVAL
            ├─ Candidate generation (vector + lexical ANN)
            ├─ Reranking (cross-encoder)
            ├─ Deduplication
            ├─ Admissibility filtering    [query returned no results]
            └─ Scoring (weighted normalised signals)
                 └─ Top-K results
                      └─ Optional: AI answer (grounded in results only)
                           └─ Provenance + citations
```

**The law, and how it is enforced.** The search pipeline never processes raw media: no loop over
videos running a vision model, no embedding a collection at query time. If a query needs something
expensive, that thing belonged in ingestion.

This is not left to discipline. `spectra_ai_core.phase` tags each model capability with the phase
it belongs to and tracks the active phase in a context variable:

| Ingestion-only | Query-safe |
|---|---|
| `ocr` · `transcribe` · `describe_image` · `embed_images` | `embed_texts` · `embed_text_for_image_space` · `rerank` · `generate` |

`IngestionService.process_job` runs inside `ingestion_phase()`; `SearchService.search` runs inside
`query_phase()`. Asking the gateway to OCR an image or transcribe audio while serving a query
raises `PhaseViolation` with a message naming the capability and pointing at this document. The
default phase is `UNSET`, which permits everything, so library use and tests are unaffected until a
caller opts in.

---

## 3. Repository layout

```
spectra/
├── apps/
│   ├── frontend/              Next.js search console
│   └── mock-enterprise/       Next.js line-of-business app (deep-link target)
│
├── packages/                  Cross-cutting contracts — no business logic
│   ├── config/                Settings, logging, budgets, model/reliability/application registries
│   ├── schemas/               Every shared type (90+ exports)
│   └── tool_contracts/        JSON Schema builders + validator
│
├── services/                  Grouped by which pipeline each package belongs to
│   │
│   ├── ingest/                PIPELINE A - writes the indexes
│   │   └── ingestion/         Extractors, chunking, per-modality pipelines, indexer
│   │
│   ├── query/                 PIPELINE B - reads the indexes
│   │   └── search/            Five-stage retrieval + unified scoring
│   │
│   ├── shared/                Used by both pipelines
│   │   ├── ai_core/           Model gateway: providers, registry, runtime manager, GPU scheduling
│   │   ├── storage/           Six stores behind interfaces, embedded + distributed backends
│   │   ├── entity_resolution/ Patterns, normalisation, the resolution cascade
│   │   └── connectors/        Source connector framework + read-only SQL guard
│   │
│   ├── api/                   FastAPI surface, container wiring
│   └── worker/                Background ingest job runner
│
├── deploy/                    Dev compose + offline-LAN operator compose + operator scripts
├── db/                        baseline/ (greenfield) + migrations/ (append-only)
├── scripts/                   Developer + release packaging scripts
├── docs/                      This documentation set
└── tests/                     unit / integration / e2e
```

Why `services/*` are separate installable packages rather than one module tree: it makes the
dependency direction *enforceable*. `spectra_search` cannot accidentally import
`spectra_ingestion`, because it does not depend on it. The dependency graph is acyclic by
construction:

```
packages/                shared/                  ingest/   query/     entry points
─────────                ───────                  ──────    ─────      ────────────
config ─┬─> schemas ─┬─> storage ──────┬────────> ingestion  ┐
        │            ├─> ai_core ──────┤                     ├─> api ─> worker
        │            ├─> entity_resolution          search ───┤
        │            └─> connectors ─────┘                   ┘
        └──> tool_contracts ───────────────────────────────────
```

**Dockerfiles live with what they build**: `services/api/Dockerfile`, `services/worker/Dockerfile`,
`apps/frontend/Dockerfile`, `apps/mock-enterprise/Dockerfile`. Python images build from the repository
root; Next.js apps build from their own directory.

---

## 4. Storage: one abstraction, two deployment shapes

Six logical stores, each with an **embedded** backend (zero infrastructure) and a **distributed**
backend (production):

| Store | Purpose | Embedded | Distributed |
|---|---|---|---|
| Vector | Dense + multimodal ANN | NumPy over SQLite | Qdrant |
| Lexical | BM25 / full-text / metadata | Real BM25 inverted index in SQLite | OpenSearch |
| Object | Content-addressed blobs | Filesystem | S3 / MinIO |
| Cache | Query, embedding, schema caches | In-process TTL map | Redis |
| Relational | Control plane (jobs, assets, sources) | SQLite | PostgreSQL |

Selected per-store from `.env`. If a distributed backend is configured but unreachable at startup,
the factory **falls back to the embedded backend and records why** — a Qdrant outage degrades
retrieval quality, it does not prevent the system from starting.

Nothing above this layer knows which backend is active.

---

## 5. Canonical references — never filesystem paths

Every reference in the system is an id or a URI:

```
source_id · asset_id · chunk_id · entity_id
object_uri = spectra://objects/<aa>/<sha256>.<ext>
```

Search is never coupled to a local path. That single decision is what lets the same index serve a
laptop with a `data/` folder and a cluster with an S3 bucket.

Ids are **content-addressed** where possible (`asset_id = f(source_id, sha256)`), which makes
re-ingestion idempotent and reindexing safe.

---

## 6. Provenance is structural, not decorative

Every retrievable unit carries a typed locator:

| Locator | Resolves to |
|---|---|
| `DocumentLocator` | document id, page, section, paragraph, character span, bbox |
| `ImageLocator` | image id, region |
| `VideoLocator` | video id, scene, frame, start/end seconds |
| `AudioLocator` | audio id, segment, start/end seconds, speaker |
| `DatabaseLocator` | source, table, primary key, record id, column |

So a result can say `Document: Incident_Report.pdf | Page: 14 | Section: Authentication`, or
`▶ Play from 01:24:17`, and the UI can open exactly that spot. No claim reaches a user without
one.

---

## 7. Model abstraction and the 24 GB constraint

The system asks for a *capability*, never a model:

```python
gateway = await get_gateway()
await gateway.embed_texts([...])          # not "load BGE-M3"
await gateway.generate(messages, role=ModelRole.DEEP_BRAIN)
```

`packages/config/resources/models.yaml` maps each **role** to ordered **candidates**
(runtime + model + VRAM cost + device). The Model Runtime Manager picks the first candidate that is
reachable and fits the profile's VRAM budget, and handles lazy loading, sequential GPU scheduling,
idle eviction, OOM recovery and CPU fallback. See [model-strategy.md](model-strategy.md) and
[4090-deployment.md](4090-deployment.md).

The last tier is **deterministic**, and it is honest about what it is: real hashed-ngram embeddings,
real IDF-weighted reranking. SPECTRA degrades into telling you less; it never degrades into making
things up.

---

## 8. The five-stage retrieval pipeline

The search pipeline progresses through five sequential stages, each a small mostly-pure function
that takes the previous stage's output and returns a payload with metrics. This design enables
tracing, testing and the Search Autopsy view.

### Stage 1: Candidate generation

Parallel: exact-ID match, BM25 (lexical), dense vector ANN, and multimodal ANN. Returns top
candidates from each retriever, filtered only by modality and date constraints at this point.

### Stage 2: Filtering

Apply source restrictions, time windows, entity filters, media-type filters, and permission
checks. Also deduplicates: when the same chunk appears in multiple candidate lists (same sentence
repeated, the same database row indexed by multiple sources), keep only the highest-scoring copy.

### Stage 3: Fusion and reranking

Reciprocal rank fusion (RRF) to blend the candidate lists from stage 2. Then cross-encoder
reranking: run the best candidates through a cross-encoder (the single strongest relevance
signal). Cost optimisation: candidates without lexical overlap or entity match skip the
cross-encoder.

### Stage 4: Scoring

Unified scoring: extract raw signals (lexical, semantic, rerank, entity match, metadata match,
source reliability, freshness) from each candidate. Apply the admissibility gate: drop candidates
with no actual evidence. Candidates are admitted if they:

- Match an exact enterprise ID (entity_match > 0), or
- Share lexical overlap with the query (lexical > 0), or
- Score ≥0.35 on the cross-encoder (paraphrase match)

This gate prevents a query for an absent term from returning five confident-looking hits. Then
min-max normalise each signal independently across the result set, weight and sum to produce the
final score. Exact-ID matches receive a +1.0 bonus; final scores live in [0, 2].

**Signals and weights:**

| Signal | Description | Weight |
|---|---|---|
| `lexical` | BM25 evidence that the query's words are in the chunk | 0.22 |
| `semantic` | Dense / multimodal ANN similarity | 0.24 |
| `rerank` | Cross-encoder score | 0.30 |
| `entity_match` | Chunk carries an enterprise id the query named | 0.12 |
| `metadata_match` | How many filter facets the chunk matches | 0.04 |
| `source_reliability` | How much the source is trusted | 0.05 |
| `freshness` | Exponential decay on the event date (180-day half-life) | 0.03 |

See `services/query/search/spectra_search/scoring.py` for the admissibility gate implementation
and measured noise ceiling table.

### Stage 5: Assembly

Build `SearchHit` objects: snippets (highlighted matches), provenance (locators pointing to the
exact location in the source), score breakdown (every signal's contribution). Return top-K hits.

---

## 9. Ingestion pipelines

Ingestion is modality-specific: documents, images, audio, video, and databases each have their own
extraction and chunking logic. All feed into a common indexer.

**Document:** PDF/DOCX/PPTX/XLSX/CSV/HTML/MD/JSON → extract blocks (with page/section provenance) →
OCR embedded images → chunk → entity extraction → embed → index.

**Image:** Single image → detect text (OCR) → describe (captioning) → chunk by region → embed →
index.

**Video:** Video file → detect scenes (ffprobe + scene detection) → extract poster frame →
optionally transcribe (ASR) → chunk by scene → embed → index.

**Audio:** Audio file → optionally transcribe (ASR) → chunk by segment → embed → index.

**Database:** SQL source → discover schema → optionally query for new rows → chunk records →
index.

Every extraction step is marked `ingestion_phase()` so it can never run at query time.

---

## 10. Search behaviour

**The core change:** search can return nothing.

Ranking signals are min-max normalised, so the best candidate always scores 1.0 on its strongest
signal however poor it is absolutely. Without the admissibility gate, a query for a name not in
the corpus scored 0.30–0.42 on semantic similarity (noise ceiling), but so did exact matches
(0.35–0.47), so the scorer could never express "nothing matched".

The gate reads raw signals before normalisation and drops anything with no actual evidence. See
section 8, stage 4.

**Answer grounding:** Every sentence must carry a citation `[N]` to a retrieved result. Uncited
sentences are dropped. If nothing is left, the answer is dropped and `degraded_reason` says why.
See `services/api/spectra_api/answering.py` and the `/api/answer` endpoint.

---

## 11. Security posture

| Surface | Control |
|---|---|
| Uploads | Size cap, MIME sniff vs extension, filename sanitisation, isolated per-job directory, AV hook |
| SQL | Single statement, SELECT-only, table allowlist, forced LIMIT, statement timeout, read-only DB role |
| Object store | URI parsing + traversal rejection + containment check |
| Connector credentials | Separate credential store, never in `connection`, redacted in every log |
| REST connectors | SSRF protection (private/loopback/metadata ranges rejected) |
| Search | `PermissionContext` threaded through every retrieval path; cache keys include the role |

See [security.md](security.md).

---

## 12. Deployment

Development is `make up`. Production for restricted networks uses the sealed-bundle model: an
image-only compose file pinned to `${APP_VERSION}`, pre-saved image tarballs, and operator scripts
for deploy / verify / rollback / patch, with all persistent state under `$APP_ROOT`.
See [deployment.md](deployment.md) and [scaling.md](scaling.md).
