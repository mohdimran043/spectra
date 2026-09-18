# SPECTRA Implementation Progress

> Evidence-Grounded Multimodal Enterprise Investigation Agent
> Updated continuously. Every meaningful milestone records what was built, what was tested,
> what failed and was fixed, and what remains.

---

## Phase 0 — Repository & environment
- [x] Repository inspected — greenfield (only `master-prompt.txt`, `docker-deployment.txt`, `.claude/`)
- [x] Environment detected — Ubuntu 24.04, 24 cores, 61 GB RAM, 222 GB free, Docker 27.5.1 + Compose v2,
      Python 3.12.7, Node 18.17.0, ffmpeg 6.1.1
- [x] **GPU status: USABLE** ✅ 2026-09-18 — the earlier NVML *"Driver/library version mismatch"*
      is resolved. `nvidia-smi` reports the RTX 4090 on driver 580.178.04 (24564 MiB, CUDA 13.0),
      `torch 2.8.0+cu128` sees the card, and `detect_gpu()` returns `available=True detail='nvml'`.
      The RTX 4090 path is now the operative default, not a fallback.
      *Remaining gap:* the NVIDIA Container Toolkit is not installed, so **containers** still cannot
      see the GPU — host processes can. Keep `GPU_ENABLED=0` for the Compose stack.
- [x] LakeSense removed from scope — SPECTRA is fully independent, with its own ingestion/indexing layer
- [x] Project skeleton created (`apps/ packages/ services/ evaluation/ demo-data/ docs/ scripts/ docker/ deploy/`)
- [x] Python venv at `.venv` (`--system-site-packages`, reuses the preinstalled torch stack)

## Phase 1 — Shared contracts (the integration seams)
- [x] `packages/config` — typed `Settings`, structured logging with request/investigation/tool-call
      correlation ids, adaptive `SearchBudget`
- [x] `packages/config/resources/models.yaml` — role→candidate model registry with per-profile VRAM budgets
- [x] `packages/config/resources/applications.yaml` — application deep-link templates + id patterns
- [x] `packages/config/resources/reliability.yaml` — configurable source-reliability model
- [x] `packages/schemas` — 96 exported contracts: provenance locators, catalog, entities, retrieval,
      evidence/claims/contradictions/timeline, investigation state + structured answer, tools,
      model runtime, permissions, content-addressed id helpers
- [x] `services/storage` interfaces — `VectorStore`, `LexicalStore`, `GraphStore`, `ObjectStore`,
      `CacheStore`, abstract `Repository`, `Storage` facade
- [x] `services/ai_core` interfaces — `LLMProvider`, `VisionProvider`, `EmbeddingProvider`,
      `RerankerProvider`, `SpeechProvider`, `OCRProvider`, abstract `ModelGateway`
- [x] `docs/api.md` — the frozen HTTP contract both frontends build against

## Phase 2 — Infrastructure & deployment  ✅ 2026-09-18
- [x] Dev compose stack (postgres, qdrant, opensearch, neo4j, redis, minio) + GPU overlay
- [x] Offline-LAN operator bundle: image-only compose pinned to `${APP_VERSION}`, `VERSION`,
      sealed release + patch workflow, `$APP_ROOT` state tree
- [x] Baseline (`db/baseline/`) + append-only migration (`db/migrations/`) split, incl. the
      `spectra_readonly` role the Database Agent connects as
- [x] Operator scripts: deploy, deploy-patch, rollback, verify, show-state, show-version,
      backup-data, run-migrations, import-images, generate-ssl, bootstrap-patch-support
- [x] Makefile with all 15 required targets plus the packaging targets
- **Audited:** `VERSION` present · no `build:` in the LAN compose · no `latest` tags · no `version:`
  key · db split present · scripts executable · 10 `CHANGE_ME` placeholders · every script passes
  `bash -n` · **both compose files validate with `docker compose config -q`**

## Phase 3 — Storage backends  ✅ 2026-09-17
- [x] Embedded: NumPy vector store, real BM25 (k1=1.5,b=0.75) over SQLite, SQLite property graph, filesystem objects, memory cache
- [x] Distributed: Qdrant, OpenSearch, Neo4j, S3/MinIO, Redis (translation layers verified; no live servers on this host)
- [x] SQLAlchemy control-plane repository (SQLite + PostgreSQL), lossless `InvestigationState` round trip
- [x] Automatic fallback to embedded when a distributed backend is unreachable
- **Tested:** 144 backend checks + 13 of my integration tests. Path traversal, edge-type allowlist,
  role-scoped filters and WAL persistence all verified.
- **Fixed:** `count()` and `health()` raised on a collection that had never been created; both now
  treat an empty index as empty rather than broken.

## Phase 4 — Model gateway (4090 profile)  ✅ 2026-09-17
- [x] Registry + candidate selection with VRAM budgeting and per-candidate rejection reasons
- [x] Providers: Ollama, vLLM/OpenAI-compatible, llama.cpp, sentence-transformers, CLIP, faster-whisper, RapidOCR/PaddleOCR/Tesseract
- [x] Deterministic tier (hashed-ngram embedding, IDF reranker, extractive synthesis) — honest, degraded-flagged
- [x] Sequential GPU scheduling, lazy load, idle eviction, OOM recovery ladder, CPU fallback
- [x] **Chain-of-thought suppression** — reasoning models emit `<think>` blocks; these are stripped at
  the provider boundary so no consumer can leak them, and Ollama is asked to skip them entirely.
- **Tested:** 76 gateway checks + a simulated-GPU scheduling/OOM suite (26 checks).

### All eight model roles are live and NOT degraded on this host
| Role | Runtime | Model | Measured |
|---|---|---|---|
| fast_brain | ollama | qwen3:8b | 6.7 s / 57 tok, correct `[E#]` citations |
| deep_brain | ollama | qwen3:30b-a3b (MoE) | 22.3 s / 320 tok ≈ 14 tok/s on CPU |
| vision | ollama | qwen2.5vl:7b | selected |
| embedding | transformers | BAAI/bge-m3 (1024-d) | cos(TX82931, matching doc)=0.77 vs 0.40 |
| mm_embedding | transformers | clip-ViT-B-32 (512-d) | shared text/image space |
| reranker | transformers | bge-reranker-v2-m3 | 0.955 relevant vs 0.00002 distractor |
| speech | faster_whisper | base (int8, CPU) | real timestamps |
| ocr | rapidocr | PP-OCRv4 (ONNX) | 330 ms, recovered TX82931/C82731/INC1829/FAILED |

Generation is genuinely generative, not extractive. The measurements above were taken **on CPU**,
before the driver was fixed; they are kept as the historical baseline. See the GPU re-measurement
below.

### GPU re-measurement  ✅ 2026-09-18
With the 4090 usable, both brain roles are 100% GPU-resident (`ollama ps` confirms the split):

| Role | Model | Resident | Processor | Decode rate | vs CPU baseline |
|---|---|---|---|---|---|
| fast_brain | qwen3:8b | 6.5 GB | 100% GPU | ~135 tok/s | ~8.5 tok/s → **16×** |
| deep_brain | qwen3:30b-a3b (MoE) | 20 GB | 100% GPU | ~159 tok/s | ~14 tok/s → **11×** |

*Decode rate* is `eval_count / eval_duration` — generation only. Cold load for the 30B MoE is
~9.6–12.6 s. At ~20 GB resident (18.6 GB declared + KV cache) the deep brain leaves ~2 GB of the
22 GB budget, so `allow_concurrent_gpu_models: false` and the eviction ladder are load-bearing
rather than theoretical — loading the deep brain evicts the fast brain.

- [x] **Full eight-role GPU benchmark** — `scripts/model_benchmark.py` measured all eight roles on
      the 4090 (every role on CUDA except OCR; Whisper promoted `base` → `large-v3` by profile
      selection alone, no config edit). Results are spliced into the README by
      `scripts/update_readme_models.py`, so the published numbers come from a run rather than from
      memory. Declared VRAM totals **42.5 GB** against the 22 GB budget.

## Phase 5 — Ingestion  ✅ 2026-09-17
- [x] Documents (PDF/DOCX/PPTX/XLSX/CSV/TXT/MD/JSON/HTML) with page/section/bbox provenance
- [x] Images (EXIF→occurred_at, OCR, caption, multimodal embedding)
- [x] Audio (transcription, timestamped semantic chunks with segment merging)
- [x] Video (scene detection incl. an ffmpeg fallback, keyframes, transcript, per-scene chunks)
- [x] Database rows → chunks, streamed in batches (a table is never materialised)
- [x] Upload security (MIME/extension validation, size cap, traversal protection, AV hook, 0700 per-job dirs)
- [x] Idempotent indexer + index versioning
- **Tested:** 61 checks against real fixtures — a real PDF (page+section+bbox+table), DOCX/PPTX/XLSX/
  CSV/HTML/JSON/MD/TXT, a PNG, a WAV, a real 3-second MP4 (3 scenes detected at 0/1/2 s), and a
  450-row table. Re-upload deduplicates; reindex does not duplicate; vectors match chunk count.
- **Rejected as designed:** oversized upload, `.exe` renamed to `.pdf`, AV-hook failure,
  `../../etc/passwd` filename.

## Phase 6 — Search  ✅ 2026-09-18
- [x] Five-stage retrieval (candidates → filter → fuse+rerank → score → assemble)
- [x] Unified scoring across seven signals, min-max normalised within the result set
- [x] Permission-aware filtering, applied *before* ranking
- [x] Text↔image↔video↔audio↔database directions
- [x] Cache keyed on query+mode+filters+top_k+role+index version+embedding identity
- **Tested:** 41 checks on fakes, then again on the real embedded stack and once more against the
  real bge-m3 / bge-reranker / CLIP models. Exact-id hits rank above every non-exact hit; a viewer
  cannot read a restricted chunk; a different role does not hit the admin cache entry.

## Phase 7 — Entity resolution  ✅ 2026-09-18
- [x] Enterprise-ID grammars + surface-variant collapsing
- [x] Cascade: exact → normalized → fuzzy → semantic → database → LLM verification
- [x] Canonical entities with accumulated aliases (immutable updates)
- [x] Cross-modal linking
- **Tested:** all five `TX82931` surface forms (`Txn 82931`, `Transaction #82931`,
  `Payment reference 82931`, `transaction 82931`) collapse to one entity id; `Mohammed Imran` /
  `M. Imran` / `Imran` collapse together; cross-modal links span document+video+image+database.

## Phase 8 — Evidence  ✅ 2026-09-18
- [x] Evidence builder (extractive summaries, never invented)
- [x] Configurable source reliability with inspectable reasons
- [x] Evidence graph (18 node labels, 12 relationship types), built incrementally
- [x] Timeline normalisation across modalities
- [x] Contradiction radar with explanation and adjudication
- [x] Evidence ledger + sufficiency + abstention support
- [x] Application resolver with URL-template validation
- **Tested:** 47 checks. Database record outranks video on reliability; a DB+PDF+video ledger
  scores diversity 0.95 vs 0.32 for three chunks of one PDF; the APPROVED/REJECTED conflict is
  detected and resolved in favour of the approved, non-superseded version *with its reasoning*;
  `TX1;DROP`, `../admin` and `TX82931/../../admin` all yield no link.
- **Fixed (cross-package):** the storage edge-type allowlist was missing `SAME_ENTITY`,
  `SUPERSEDES` and `OPENED_AS`, so entity merging and application linking failed at write time.
  The two vocabularies are now asserted equal.

## Phase 9 — The Brain  ✅ 2026-09-18

> **Partly superseded by Phase 16 (2026-09-18).** The competing-hypothesis engine described in this
> phase was removed and replaced by the claim builder; the record below is kept as history of what
> was built and measured at the time. Everything else in this phase still stands.

- [x] Query understanding (rule router + optional LLM refinement)
- [x] 22 real callable tools with JSON schemas, validation, timeouts, telemetry
- [x] Dynamic iterative loop (plan → act → observe → replan → sufficiency → verify)
- [x] Hypothesis engine with the six-state lifecycle
- [x] Disproof agent (mandatory disconfirming search)
- [x] Verifier
- [x] Grounded synthesis with citation checking + abstention
- [x] Query explanation, search autopsy, trace streaming
- [x] Fast mode / Deep mode, budget enforcement, graceful degradation on disabled agents
- **Tested:** 54 checks. Fast mode makes ≤5 tool calls and never touches the deep brain; deep mode
  runs ≥2 iterations with ≥3 competing hypotheses, a disproof probe and verification; a single weak
  item produces abstention; disabling the Vision Agent degrades cleanly with named alternatives;
  budget exhaustion stops cleanly and still answers; contradictory evidence flips a hypothesis.
- **Fixed after integration:** hypotheses were mined from *any* retrieved text, so generic pages
  that never name the focal entity seeded plausible-but-unfounded explanations and, being numerous,
  outranked the one page that did name it. Generation is now grounded to the focal entity, with a
  documented fallback to the full set (which should end in abstention, not in zero hypotheses).

## Phase 10 — Connectors  ✅ 2026-09-17
- [x] Generic `SourceConnector` framework + registry (extensible without touching the agent)
- [x] Local folder, S3/MinIO, PostgreSQL, MySQL, SQLite, REST/JSON API, upload
- [x] Read-only SQL guard (single statement, SELECT-only, table allowlist, forced LIMIT, timeout, audit)
- [x] Credential store with redaction; SSRF protection on REST
- **Tested:** 47 checks. Every one of these was rejected *and audited*: `DROP`, `DELETE`, `UPDATE`,
  stacked `SELECT 1; DROP`, comment-obfuscated `-- \n; UPDATE`, `INTO OUTFILE`, `ATTACH DATABASE`,
  off-allowlist table, `UNION SELECT` into a forbidden table, `/*!50000 SELECT*/`, `SEL/**/ECT`,
  `pg_catalog.pg_shadow`. Missing `LIMIT` injected; `LIMIT 100000` lowered to the cap; 1 s statement
  timeout interrupted a runaway query; `verify_read_only()` proved the role cannot write.
- Also rejected: `../../etc/passwd`, an escaping symlink, and `http://169.254.169.254/` (cloud metadata).

## Phase 11 — API & worker  ✅ 2026-09-18
- [x] FastAPI app: 16 routers covering search, uploads, assets, investigations, cases, entities,
      evidence, graph, sources, models, agents, database, demo, evaluation, health, stream
- [x] SSE trace streaming with replay from `Last-Event-ID`, heartbeat and terminal detection
- [x] Health + Prometheus/JSON metrics
- [x] Async worker with bounded concurrency
- [x] Markdown/JSON case-report export
- **All ten services wire with zero non-model degradation.**
- **Fixed:** `Depends` in both `Annotated` and a default (FastAPI rejects it) · `JSONResponse`
  positional-argument order, which had broken *every* error path · a 204 route returning a body ·
  container wiring against constructor signatures that differed from the ones I specified.

## Phase 12 — Frontends
- [ ] Investigation console (Impeccable-driven design)
- [x] **Mock enterprise application on the same database** ✅ 2026-09-17 — Next.js 14.2.35,
  SQLite *and* PostgreSQL backends both verified against real databases; `tsc`/lint/build all clean;
  zero hard-coded identifiers (`grep` proves it); malformed ids rejected before reaching the driver;
  a database outage renders an explicit error rather than sample data.

## Phase 13 — Demo data & evaluation  ✅ 2026-09-18
- [x] Seeded multimodal enterprise dataset with a coherent investigation story
- [x] Benchmark suite across all 16 mandated categories (54 questions)
- [x] Five baselines (BM25, vector RAG, multimodal RAG, agentic, SPECTRA)
- [x] Metrics + runner + report, with an explicit "Where SPECTRA loses" section
- **Generated and verified:** 24 documents, 12 images, 3 audio, 3 videos, 120 customers,
  941 transactions, 14 incidents, 25 assets. The MP4s are real H.264/AAC; the WAVs are real with
  sidecar ground-truth transcripts; the PDFs place the key finding on a genuinely late page.
- **Manifest-driven:** ids are generated, not hard-coded — seed 42 produced `C38198` / `TX83155` /
  `INC9344`, and every benchmark question resolves through the manifest.
- **Metrics tested:** 28 unit tests against hand-computed values, including nDCG = 1/log₂3 for a
  single relevant item at rank 2, and the four abstention outcomes.

## Phase 14 — Testing & documentation
- [ ] Unit / integration / end-to-end tests
- [ ] Five acceptance scenarios from the spec
- [ ] Full documentation set

---

## Phase 15 — GPU enablement, structure and enforcement  ✅ 2026-09-18

- [x] All eight roles CUDA-resident under a 21 GB usable budget, zero degraded reasons
- [x] **Every model role measured** — `scripts/model_benchmark.py`; the README table is generated by
      `scripts/update_readme_models.py` from that JSON, so published numbers cannot drift
- [x] Dockerfiles moved out of `docker/` to live with what they build; the Next.js apps build from
      their own directory (context ~384 kB instead of the whole tree) and carry their own
      `.dockerignore`. Verified by actually building `spectra-mock-enterprise` from the new location.
- [x] Service packages regrouped by pipeline — `services/ingest/`, `services/query/`,
      `services/shared/` — so the tree answers "what does ingestion and what does search".
      Zero import changes: only `pyproject` package discovery moved.
- [x] Each agent split into its own folder under `agents/`: document, vision, video, audio,
      database, graph, entity_resolver, hypothesis (renamed `claim_builder` in Phase 16), disproof,
      verifier, timeline, contradiction, brain. Shared tool infrastructure stayed in `tools/`. Tool inventory verified identical
      (22 tools, 12 agent values, same flags/timeouts/costs).
- [x] **The ingestion/query split is enforced, not documented**: `spectra_ai_core.phase` refuses
      `ocr` / `transcribe` / `describe_image` / `embed_images` on the query path. 16 tests, including
      through the real gateway.

### Defects found and fixed while enabling the GPU

1. **faster-whisper CUDA aborted the process.** CTranslate2 `dlopen`s cuDNN itself and calls
   `abort()` when it is absent — a native crash, not a catchable exception, which killed the
   benchmark outright. Added `cuda_libs.py` (RTLD_GLOBAL preload of the pip-installed NVIDIA
   wheels) plus an availability probe, so a host without cuDNN selects the CPU candidate rather
   than dying. Whisper large-v3 now runs on CUDA: 3 s of audio in ~320 ms.
2. **Ollama eviction freed no VRAM.** `unload()` only closed the HTTP client; ollama keeps weights
   in its own process on a 5-minute timer. Three of the eight roles are ollama-hosted, so the
   scheduler's VRAM accounting was fiction. Now sends `keep_alive: 0` — measured 6355 → 335 MiB.
3. **`unload_role` did not exist** although `POST /api/models/{role}/unload` called it; that
   endpoint would have returned 500. Implemented, and added to the gateway contract.
4. **MinIO images no longer pull from Docker Hub** (the project moved to quay.io). Every reference
   corrected, with a comment so it is not reverted.
5. **`tests/e2e` failed at collection** — a missing package marker made `from .conftest import ...`
   an error, so the acceptance scenarios never ran. Fixed; 154 tests now collect.

Defect 2 also produced a false measurement: `mm_embedding` first timed at 7.98 s per image when raw
CLIP does it in 4.8 ms. It was contending with a 20 GB ollama model the scheduler believed it had
evicted. After the fix it measures **9 ms** — a reminder that a number which looks wrong usually is.

## Phase 16 — Claims replace competing hypotheses  ✅ 2026-09-18

The competing-hypothesis engine was removed at the user's request and replaced with a claim-centric
design. This is a behaviour change, not a rename.

**Why.** The engine generated competing explanations, scored them against each other and normalised
their confidences so the candidate set summed to about 1. A correct conclusion competing with six
weak alternatives therefore peaked at about 16% confidence, fell below the sufficiency threshold,
and the system abstained on questions it had in fact answered correctly. That was the last entry
under Known Issues; entity grounding (Phase 9) reduced it but could not remove it, because the
division is in the scoring model rather than in the candidate set. A confidence split between candidates measures
how many alternatives were imagined, not how well the evidence backs the answer.

**What replaces it.** The `claim_builder` agent derives claims directly from the retrieved evidence,
grounded to the investigation's focal entity. Each claim is judged on its own evidence alone:
supporting weight, independent-source count and evidence diversity, minus a contradiction penalty.
No competition, no normalisation, so a well-supported conclusion keeps a high confidence.

**What did not change.** The disproof agent is still mandatory and is now the load-bearing guard
against over-confidence: it probes the leading claim (`leading_claim()`), and a claim its probe
knocks down becomes `refuted` and drops out. Abstention keeps its own `AnswerStatus` and the
benchmark suite keeps sixteen categories (`hypothesis_testing` became `claim_verification`).

- [x] `Hypothesis` / `HypothesisStatus` deleted; `Claim` / `ClaimStatus`
      (`supported · weak · contradicted · refuted · insufficient`) in their place — "disproved"
      is now "refuted"
- [x] `InvestigationState.hypotheses` → `claims`; `leading_hypothesis()` → `leading_claim()`;
      `InvestigationAnswer.hypotheses` → `claims`
- [x] `claims_made` / `claims_refuted` on the autopsy and metrics, `claim_count` on the case,
      `claim_ids` on evidence, `claim_id` in `spectra_schemas.ids`
- [x] Agent `hypothesis_engine` → `claim_builder`, flag `hypothesis` → `claim`,
      `AgentName.HYPOTHESIS` → `AgentName.CLAIM`,
      `ENABLE_HYPOTHESIS_ENGINE` → `ENABLE_CLAIM_BUILDER` (`enable_claim_builder`)
- [x] `Hypothesis` dropped from the graph vocabulary: 17 node labels, 12 relationship types
- [x] Documentation set updated — `README.md`, `docs/agent-design.md` (the loop is now
      understand → plan → retrieve → build claims → sufficient? → disproof the leading claim →
      contradictions → verify → synthesise), `docs/api.md`, `docs/architecture.md`,
      `docs/data-model.md`, `docs/demo-guide.md`, `docs/evaluation.md`, `docs/scaling.md`,
      `docs/search-architecture.md`

## Current State

Phases 0–11 and 13 are complete and tested: contracts, storage, model gateway, ingestion, search,
entity resolution, evidence, the Brain, connectors, the API/worker layer, and the demo dataset plus
evaluation harness. The reasoning layer is claim-centric as of Phase 16. The RTX 4090 is usable as
of 2026-09-18, so the model gateway runs its CUDA candidates rather than its CPU fallbacks.

Outstanding: the analyst investigation console (Phase 12) and the consolidated test/documentation
pass (Phase 14).

## Known Issues

- **Containers cannot see the GPU.** The host GPU works, but the NVIDIA Container Toolkit is not
  installed, so `docker info` lists only `runc`. Host processes get the 4090; the Compose stack does
  not. Keep `GPU_ENABLED=0` until `nvidia-ctk runtime configure --runtime=docker` has been run,
  otherwise `up` fails with `could not select device driver "nvidia" with capabilities: [[gpu]]`.
- **No local GGUF weights.** `./models` is effectively empty (4 KB); the live generative path is the
  **Ollama** daemon (`qwen3:8b`, `qwen3:30b-a3b`, `qwen2.5vl:7b`). The llama.cpp candidates in
  `models.yaml` are unexercised until those files are fetched.
- The deterministic extractive tier remains the final rung of the fallback ladder. It is no longer
  the operative default, but it is still what answers degrade *to* when no runtime is reachable.
- `qwen3:30b-a3b` reports `5%/95% CPU/GPU` in `ollama ps`: at 18.6 GB declared it does not fully fit
  beside the other resident roles, so ollama offloads a slice. It works and the scheduler evicts to
  make room, but a deep-mode answer costs ~5 s rather than the ~2 s a fully-resident model would.
- Confidence is no longer divided between candidates (Phase 16), which removes the systematic
  under-claiming that used to push correct conclusions below the sufficiency threshold. What remains
  is ordinary threshold sensitivity: a claim whose support is thin, non-independent or drawn from one
  modality still scores low and still abstains. That is intended behaviour rather than a defect, and
  the `claim_verification` and abstention benchmark categories are where it is measured.

## Next Tasks

1. Land the eleven parallel streams and reconcile any interface drift against the frozen contracts.
2. Wire the API layer over the landed services.
3. Generate the demo dataset, ingest it, and run the five acceptance scenarios end to end.
4. Complete the test suite and the documentation set.
