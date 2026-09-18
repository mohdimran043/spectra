# SPECTRA — Architecture

SPECTRA is an agentic enterprise investigation platform. It autonomously investigates questions
across documents, images, audio, video, structured databases and configurable external sources. It
resolves entities across modalities, builds evidence-grounded claims, retrieves supporting
*and disconfirming* evidence, detects contradictions, reconstructs timelines, maintains an evidence
graph, verifies conclusions, exposes provenance, and links discovered entities to enterprise
application records.

It is designed to run completely on a single RTX 4090 (24 GB) and to scale to TB-scale corpora and
billions of rows **without a rewrite**.

---

## 1. The organising principle

Seven things are independently replaceable. A change to one must not force a rewrite of another:

```
INGESTION   SEARCH   AGENT   MODELS   GRAPH   APPLICATION   UI
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
                           └─ Chunking / scene segmentation
                                └─ Entity extraction
                                     └─ Embeddings
                                          └─ Search indexes (vector + lexical)
                                               └─ Knowledge / evidence graph
```

### Pipeline B — search / investigation (cheap, online, per query)

```
User query / image upload
  └─ Query understanding
       └─ SPECTRA BRAIN
            ├─ Plan
            ├─ Select tools & sources
            ├─ Retrieve evidence          (reads indexes only)
            ├─ Entity resolution
            ├─ Evidence graph
            ├─ Build claims from the evidence
            ├─ Support search + disproof search
            ├─ Contradiction check
            ├─ Verify
            └─ Confidence decision
                 └─ Answer + evidence + provenance
                      └─ Enterprise application links
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

That is what makes the TB-scale claim credible rather than aspirational: it is checkable, and the
test suite checks it.

---

## 3. Repository layout

```
spectra/
├── apps/
│   ├── frontend/              Next.js investigation console · Dockerfile
│   └── mock-enterprise/       Next.js line-of-business app (the deep-link target) · Dockerfile
│
├── packages/                  Cross-cutting contracts — no business logic
│   ├── config/                Settings, logging, budgets, model/reliability/application registries
│   ├── schemas/               Every shared type (96 exports)
│   └── tool_contracts/        JSON Schema builders + validator for agent tools
│
├── services/                  Grouped by which pipeline each package belongs to
│   │
│   ├── ingest/                PIPELINE A - writes the indexes
│   │   └── ingestion/         Extractors, chunking, per-modality pipelines, indexer
│   │
│   ├── query/                 PIPELINE B - reads the indexes, never the raw objects
│   │   ├── search/            Five-stage retrieval + unified scoring
│   │   ├── evidence/          Ledger, reliability, graph, timeline, contradictions, app resolver
│   │   └── agent/             The Brain: understanding, tools, claims, disproof, verifier
│   │
│   ├── shared/                Used by both pipelines
│   │   ├── ai_core/           Model gateway: providers, registry, runtime manager, GPU scheduling
│   │   ├── storage/           Six stores behind interfaces, embedded + distributed backends
│   │   ├── entity_resolution/ Patterns, normalisation, the resolution cascade
│   │   └── connectors/        Source connector framework + read-only SQL guard
│   │
│   ├── api/                   FastAPI surface, SSE streaming, container wiring · Dockerfile
│   └── worker/                Background ingest job runner · Dockerfile
│
├── evaluation/                Benchmarks, baselines, metrics, runners, reports
├── demo-data/                 Seeded multimodal dataset generator + ground truth
├── deploy/                    Dev compose + offline-LAN operator compose + operator scripts
├── db/                        baseline/ (greenfield) + migrations/ (append-only)
├── scripts/                   Developer + release packaging scripts
├── docs/                      This documentation set
└── tests/                     unit / integration / e2e
```

Why `services/*` are separate installable packages rather than one module tree: it makes the
dependency direction *enforceable*. `spectra_search` cannot accidentally import
`spectra_agent`, because it does not depend on it. The dependency graph is acyclic by construction:

```
packages/                shared/                    ingest/    query/         entry points
─────────                ───────                    ───────    ──────         ────────────
config ─┬─> schemas ─┬─> storage ──────────┬──────> ingestion ──┐
        │            ├─> ai_core ──────────┤                    ├─> api ─> worker
        │            ├─> entity_resolution ┼──────> search ─────┤
        │            └─> connectors ───────┘        evidence ───┤
        └──> tool_contracts ───────────────────────> agent ─────┘
```

**Dockerfiles live with what they build**: `services/api/Dockerfile` (which also produces the
worker via a `worker` target), `services/worker/Dockerfile`, `apps/frontend/Dockerfile` and
`apps/mock-enterprise/Dockerfile`. The Python images build from the repository root because they
install the whole monorepo; the Next.js apps build from their own directory, so their context is
a few hundred kilobytes rather than the entire tree.

---

## 4. Storage: one abstraction, two deployment shapes

Six logical stores, each with an **embedded** backend (zero infrastructure) and a **distributed**
backend (production):

| Store | Purpose | Embedded | Distributed |
|---|---|---|---|
| Vector | dense + multimodal ANN | NumPy over SQLite | Qdrant |
| Lexical | BM25 / full-text / metadata | real BM25 inverted index in SQLite | OpenSearch |
| Graph | entity / evidence graph | SQLite property graph | Neo4j |
| Object | content-addressed blobs | filesystem | S3 / MinIO |
| Cache | query, embedding, schema caches | in-process TTL map | Redis |
| Relational | control plane | SQLite | PostgreSQL |

Selected per-store from `.env`. If a distributed backend is configured but unreachable at startup,
the factory **falls back to the embedded backend and records why** — a Qdrant outage degrades
retrieval quality, it does not prevent the system from starting.

Nothing above this layer knows which backend is active.

---

## 5. Canonical references — never filesystem paths

Every reference in the system is an id or a URI:

```
source_id · asset_id · chunk_id · entity_id · evidence_id · frame_id
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
| `DocumentLocator` | document id, page, section, paragraph, char span, bbox |
| `ImageLocator` | image id, region |
| `VideoLocator` | video id, scene, frame, start/end seconds |
| `AudioLocator` | audio id, segment, start/end seconds, speaker |
| `DatabaseLocator` | source, table, primary key, record id, column |
| `ExternalLocator` | source, resource, record |

So a result can say `Document: Incident_Report.pdf | Page: 14 | Section: Authentication`, or
`▶ Play from 01:24:17`, and the UI can open exactly that spot. No claim reaches a user without one.

---

## 7. Model abstraction and the 24 GB constraint

The agent asks for a *capability*, never a model:

```python
gateway = await get_gateway()
await gateway.embed_texts([...])        # not "load BGE-M3"
await gateway.generate(messages, role=ModelRole.DEEP_BRAIN)
```

`packages/config/resources/models.yaml` maps each **role** to ordered **candidates**
(runtime + model + VRAM cost + device). The Model Runtime Manager picks the first candidate that is
reachable and fits the profile's VRAM budget, and handles lazy loading, sequential GPU scheduling,
idle eviction, OOM recovery and CPU fallback. See [model-strategy.md](model-strategy.md) and
[4090-deployment.md](4090-deployment.md).

The last tier is **deterministic**, and it is honest about what it is: real hashed-ngram embeddings,
real IDF-weighted reranking, and *extractive* (not generative) synthesis — every response flagged
`degraded` with the reason. SPECTRA degrades into telling you less; it never degrades into making
things up.

---

## 8. The Brain

Not a chatbot and not a fixed script — a dynamic loop over an explicit, serialisable state machine:

```
understand → plan → select tools → execute (parallel where independent)
   → observe → update evidence / entities / graph → build claims
   → sufficient? ──no──> replan (more tools, or more claims) ─────┐
                 └─yes─> disproof the leading claim → contradictions
                         → verify → synthesise
   ^───────────────────────────────────────────────────────────────┘
```

State lives in `InvestigationState` (serialisable, persisted every iteration). Transitions produce
new objects; nothing is mutated in place. See [agent-design.md](agent-design.md).

---

## 9. What makes it a research platform

The architecture is arranged so these are each independently measurable:

1. cross-modal entity resolution
2. evidence-centric investigation
3. evidence-grounded claim construction
4. disconfirming-evidence search
5. contradiction-aware reasoning
6. temporal evidence reasoning
7. adaptive retrieval budgets
8. evidence sufficiency and abstention
9. latency vs accuracy
10. multimodal vs single-modal baselines

`evaluation/` implements five selectable strategies over the same corpus — BM25, vector RAG,
multimodal RAG, agentic retrieval, and full SPECTRA — so each capability above can be ablated.
See [evaluation.md](evaluation.md).

---

## 10. Security posture

| Surface | Control |
|---|---|
| Uploads | size cap, MIME sniff vs extension, filename sanitisation, isolated per-job directory, AV hook |
| SQL | single statement, SELECT-only, table allowlist, forced LIMIT, statement timeout, full audit trail, read-only DB role |
| Object store | URI parsing + traversal rejection + containment check |
| Connector credentials | separate credential store, never in `connection`, redacted in every log |
| REST connectors | SSRF protection (private/loopback/metadata ranges rejected) |
| Application links | id pattern validation, URL encoding, base containment, existence verified before emission |
| Search | `PermissionContext` threaded through every retrieval path; cache keys include the role |
| Graph (Neo4j) | relationship types validated against an allowlist before Cypher interpolation |

See [security.md](security.md).

---

## 11. Deployment

Development is `make up`. Production for restricted networks uses the sealed-bundle model: an
image-only compose file pinned to `${APP_VERSION}`, pre-saved image tarballs, and operator scripts
for deploy / verify / rollback / patch, with all persistent state under `$APP_ROOT`.
See [deployment.md](deployment.md) and [scaling.md](scaling.md).
