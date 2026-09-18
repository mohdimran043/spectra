# Changelog

All notable changes to SPECTRA are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The version in `VERSION` is the single source of truth for image tags, bundle names
and the `APP_VERSION` environment variable. Bump it with
`make version-bump V=patch|minor|major`, then add a section here before packaging.

## [Unreleased]

### Removed

- **The Contradiction Radar, in full.** Nothing compares evidence pairs any more. Deleted: the
  `contradiction` agent package and its `detect_contradictions` tool, the `ContradictionRadar`
  detector in the evidence layer, the `Contradiction` model, `AnswerStatus.CONTESTED`,
  `AgentName.CONTRADICTION`, `QueryIntent.CONTRADICTION`, the `contradiction_prf` evaluation
  metric, the `contradiction_count` column on `investigation_cases`, and the
  `ContradictionRadar` panel in the console.
- `contradictions` is gone from `InvestigationState`, `InvestigationMetrics`, `SearchAutopsy`,
  `InvestigationAnswer` and `InvestigationCase`, and from the case-report Markdown.

### Changed

- The investigation loop is now **plan → retrieve → observe → replan → disproof → verify →
  synthesise**. The contradiction sweep that used to sit between disproof and verification is gone.
- The Verifier still runs four mandatory checks, but the third is now **`no_counter_evidence`**
  (was `no_unresolved_contradiction`). It asks the evidence directly — did the disproof probe turn
  up anything among the cited items? — instead of consulting the radar.
- Questions phrased as "the sources disagree about X" now classify as `QueryIntent.INVESTIGATION`
  and run the full loop, rather than routing to a detector that no longer exists.
- `Claim.contradicting_evidence` survives, but the disproof probe is now its only producer. The
  console labels it "found against it by the disproof probe" rather than "contradicting", and the
  claim card shows supporting exhibits first.
- The benchmark category `contradiction_detection` is renamed **`conflicting_sources`**. The corpus
  still plants two disagreeing approval memos; what is measured is now that SPECTRA refuses to
  assert either side as settled, not that it emits a contradiction object.
- The guided demo's "Contradiction Radar" scenario is replaced by **"Knowing When To Stop"**, which
  demonstrates abstention against a question the corpus cannot answer.
- Investigations persisted before this change are upgraded on read: `contradictions`, the
  `contradictions` metric and `contradiction_radar` trace steps are dropped, and a stored
  `contested` answer status is re-read as `partially_supported`.

### Fixed

- `investigation_cases` was never rebuilt after the hypothesis→claim refactor and still carried a
  `hypothesis_count` column with no `claim_count`. The table was empty, so no data was lost, but
  any write to it would have failed. It is now dropped and recreated from the current model.

### Added

- **Claims.** The `claim_builder` agent derives claims directly from the evidence an investigation
  retrieved, grounded to its focal entity, and judges each one **on its own evidence alone**:
  supporting weight, independent-source count and evidence diversity, minus a penalty for whatever
  the disproof probe found against it.
  There is no competition between claims and no normalisation across them, so a well-supported
  conclusion keeps a high confidence.
- `Claim` and `ClaimStatus` (`supported` · `weak` · `contradicted` · `refuted` · `insufficient`;
  what was called "disproved" is now **refuted**). A claim carries `claim_id` (`C1`, `C2`, …),
  `text`, `confidence`, `status`, `supporting_evidence`, `contradicting_evidence`, `disproof_probe`,
  `disproof_searched`, `verified`, `verification_note` and `rationale`, plus the derived
  `evidence_ids` and `confidence_label`.

### Changed

- The disproof agent keeps its status — still mandatory — and now probes **the leading claim**
  (`InvestigationState.leading_claim()`), asking what evidence would show it is wrong. With nothing
  else competing for confidence, the disconfirming search is what keeps it honest: a claim the probe
  knocks down becomes `refuted` and drops out of consideration. Abstention is unchanged and still
  first-class.
- Renamed across the contract:

| Was | Is |
|---|---|
| `InvestigationState.hypotheses` | `claims` |
| `InvestigationState.leading_hypothesis()` | `leading_claim()` |
| `InvestigationAnswer.hypotheses` | `claims` |
| `hypotheses_generated` / `hypotheses_disproved` (`SearchAutopsy`, `InvestigationMetrics`) | `claims_made` / `claims_refuted` |
| `InvestigationCase.hypothesis_count` | `claim_count` |
| `EvidenceItem.hypothesis_ids` | `claim_ids` |
| agent `hypothesis_engine`, flag `hypothesis`, `AgentName.HYPOTHESIS` | `claim_builder`, flag `claim`, `AgentName.CLAIM` |
| `ENABLE_HYPOTHESIS_ENGINE` / `enable_hypothesis_engine` | `ENABLE_CLAIM_BUILDER` / `enable_claim_builder` |
| benchmark category `hypothesis_testing` | `claim_verification` (still sixteen categories) |
| `spectra_schemas.ids.hypothesis_id` | `claim_id` |
| SSE `event: hypotheses` | `event: claims` |

- GPU documentation now reflects a **working RTX 4090** on the development host. The NVML
  *"Driver/library version mismatch"* is resolved (driver 580.178.04, CUDA 13.0,
  `torch 2.8.0+cu128`); `detect_gpu()` reports `available=True detail='nvml'` and
  `MODEL_PROFILE=rtx4090` is the operative profile rather than an aspiration.
- Recorded measured GPU throughput in place of the CPU-era baseline: `qwen3:8b` ~135 tok/s
  (6.5 GB resident) and `qwen3:30b-a3b` ~159 tok/s (20 GB resident), both 100% GPU, against
  ~8.5 and ~14 tok/s on CPU. The CPU figures are retained in `progress.md` as history.
- Documented that GPU access stops at the host boundary: the NVIDIA Container Toolkit is not
  installed, so `docker info` lists only `runc` and the Compose stack must keep `GPU_ENABLED=0`
  until `nvidia-ctk runtime configure --runtime=docker` has been run.
- Reframed the extractive deterministic tier as the last rung of the fallback ladder rather than
  the default synthesis mode.
- Regenerated the README model table from a real eight-role GPU benchmark
  (`scripts/model_benchmark.py` → `scripts/update_readme_models.py`): every role resolves to CUDA
  except OCR, and Whisper is promoted `base` → `large-v3` by profile selection alone. Declared VRAM
  totals 42.5 GB against the 22 GB budget, which is the scheduling rationale stated as data.
- Noted the measurement methodology explicitly so the per-doc figures do not read as contradictory:
  decode rate is `eval_count / eval_duration`, warm call includes prompt evaluation, and resident
  VRAM exceeds declared VRAM by the KV cache.

### Removed

- **The competing-hypothesis engine**, at the user's request. It generated rival explanations, scored
  them against each other and normalised their confidences so the candidate set summed to about 1.
  That arithmetic was the defect: a correct conclusion competing with six weak alternatives peaked
  near 16% confidence, fell below the sufficiency threshold, and the system abstained on questions it
  had in fact answered correctly. A score divided between candidates measures how many alternatives
  were imagined, not how well the evidence backs the answer.
- With it: `Hypothesis`, `HypothesisStatus`, the `predicted_signals` mechanism, and the `Hypothesis`
  graph node label (the vocabulary is now seventeen node labels and twelve relationship types).
  The `[1.0.0]` entries below still describe the hypothesis engine, because that is what 1.0.0
  shipped; they are history, not current behaviour.

Documents touched: `README.md`, `progress.md`, `docs/agent-design.md`, `docs/api.md`,
`docs/architecture.md`, `docs/data-model.md`, `docs/demo-guide.md`, `docs/evaluation.md`,
`docs/scaling.md`, `docs/search-architecture.md`, `docs/4090-deployment.md`, `docs/deployment.md`,
`apps/frontend/PRODUCT.md`.

## [1.0.0] - 2026-09-17

### Added

- Initial SPECTRA release: hypothesis-driven multimodal enterprise investigation platform.
- API service (`spectra-api`, FastAPI/uvicorn on port 8000) and background worker
  (`spectra-worker`, `python -m spectra_worker`).
- Analyst frontend (`spectra-frontend`, Next.js, port 3000) and the mock enterprise
  application (`spectra-mock-enterprise`, Next.js, port 3001).
- Distributed storage backends: PostgreSQL 16, Qdrant, OpenSearch 2.x, Neo4j 5,
  Redis 7 and MinIO.
- Offline LAN deployment layer: image-only `deploy/docker-compose.lan.yml`, sealed
  release bundles, patch bundles, and the operator script set under `deploy/scripts/`.
- Control-plane database baseline (`db/baseline/001_control_plane.sql`) and the
  enterprise demo schema with a dedicated read-only role
  (`db/baseline/002_enterprise_demo.sql`).
- Ordered, append-only migration stream under `db/migrations/`.

#### Ingestion

- Document extraction for PDF, DOCX, PPTX, XLSX, CSV, TXT, Markdown, JSON and HTML with
  page, section, paragraph and bounding-box provenance preserved end to end.
- Image ingestion: EXIF metadata (including `DateTimeOriginal` as the event time), OCR,
  vision captioning and multimodal embedding.
- Audio ingestion: transcription with word-level timestamps, merged into semantic chunks
  that retain their start and end offsets.
- Video ingestion: scene detection (PySceneDetect with an ffmpeg fallback and a uniform
  final fallback), keyframe extraction, per-scene transcript and visual chunks.
- Database ingestion: rows streamed in batches and serialised into retrievable chunks.
- Upload security: size cap, MIME sniffing cross-checked against the extension, filename
  sanitisation, isolated per-job directories (mode 0700) and an antivirus hook.
- Content-addressed deduplication and an idempotent indexer with index versioning.

#### Retrieval

- Five-stage pipeline: candidate generation, filtering, reciprocal-rank fusion plus
  cross-encoder reranking, unified scoring, assembly.
- A real BM25 implementation whose tokeniser keeps alphanumeric identifiers such as
  `TX82931` intact rather than splitting them.
- Seven-signal scoring kept separately on every hit so ranking stays inspectable.
- Permission filtering applied before ranking, with the role folded into every cache key.

#### Entity resolution

- Enterprise identifier grammars with surface-variant collapsing.
- A six-step cascade: exact, normalized, fuzzy, semantic, database, then LLM verification
  only when the top candidates are within the ambiguity margin.
- Cross-modal linking, so one entity resolves across documents, video, images and rows.

#### Evidence and reasoning

- Evidence ledger with extractive summaries, configurable source reliability and an
  inspectable reason string for every score.
- Evidence graph over 18 node labels and 12 relationship types, built incrementally.
- Timeline normalisation across database, document, media-offset and EXIF timestamps.
- Contradiction radar: value, polarity and temporal-impossibility detection, adjudicated
  by version status, recency, reliability and specificity — and always explained.
- Evidence diversity as a first-class quantity, so independent corroboration outweighs
  volume from a single source.

#### The agent

- Twenty-two callable tools with JSON schemas, validation, timeouts and telemetry.
- A dynamic plan/act/observe/replan loop over a serialisable `InvestigationState`.
- Hypothesis engine with a six-state lifecycle, grounded to the investigation's focal
  entity so generic text cannot seed an unfounded explanation.
- A mandatory disproof agent that actively searches for refuting evidence.
- Verifier, grounded synthesis with post-hoc citation checking, and abstention as a
  first-class outcome.
- Search autopsy, query explanation and SSE trace streaming.

#### Models

- Capability-oriented model gateway: roles map to ordered candidates, and no application
  code names a model, runtime or device.
- Providers for Ollama, vLLM/OpenAI-compatible endpoints, llama.cpp, sentence-transformers,
  CLIP, faster-whisper, RapidOCR, PaddleOCR and Tesseract.
- Sequential GPU scheduling within a VRAM budget, lazy loading, idle eviction and a
  five-rung OOM recovery ladder.
- A deterministic tier — real hashed-ngram embeddings, real IDF reranking and extractive
  synthesis — used when nothing else is reachable, always flagged as degraded.

#### Research

- Benchmark suite across sixteen categories, driven by a generated manifest so no
  identifier is hard-coded.
- Five selectable strategies: BM25, vector RAG, multimodal RAG, agentic retrieval and full
  SPECTRA; the agentic-to-SPECTRA comparison isolates what hypotheses, disproof and
  verification contribute.
- Retrieval, resolution, evidence, reasoning and calibration metrics, and a report that
  always includes a "Where SPECTRA loses" section.

### Security

- Read-only SQL guard: single statement, `SELECT` only, table allowlist, forced `LIMIT`,
  statement timeout and a full audit trail on success and failure alike.
- Object-store URIs are parsed and confined; path traversal is rejected before any I/O.
- Connector credentials live in a separate store, never in the source descriptor, and are
  redacted from every log line.
- SSRF protection on REST connectors, including the cloud metadata range.
- Graph relationship types and node labels are validated against allowlists before being
  interpolated into Cypher.
- Application deep links are emitted only for ids that match their configured pattern and
  are verified to exist.
- Model chain-of-thought is stripped at the provider boundary and never reaches a consumer.
- Every secret is supplied through `.env`; images and compose files ship only
  `CHANGE_ME` placeholders, and `deploy.sh` refuses to start while any remain.
- The Database Agent connects to the enterprise demo database through the
  `spectra_readonly` role, which holds `SELECT` and nothing else.
- All application containers run as a non-root user.

[Unreleased]: https://example.invalid/spectra/compare/v1.0.0...HEAD
[1.0.0]: https://example.invalid/spectra/releases/tag/v1.0.0
