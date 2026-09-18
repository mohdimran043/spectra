# SPECTRA API Contract

Base URL: `http://localhost:8000`. All payloads are JSON unless stated.
Every response carries `X-Request-ID`.

Authentication in development is a header-based role shim:

```
X-Spectra-User: <user id>        # optional, defaults to "local-user"
X-Spectra-Role: admin|analyst|viewer   # defaults to DEFAULT_ROLE
```

This is deliberately a thin `PermissionContext` factory so OAuth/OIDC/Keycloak can replace it
without touching any retrieval or indexing code.

---

## 1. Health & system

### `GET /api/health`

Returns `HealthReport`:

```json
{
  "status": "ok|degraded|error",
  "version": "1.0.0",
  "deployment_mode": "development",
  "degraded": false,
  "checked_at": "2026-09-18T11:41:21.481103Z",
  "backends": {
    "relational": "sqlite",
    "vector": "embedded"
  },
  "components": {
    "vectors":    {"backend": "embedded", "status": "ok"},
    "lexical":    {"backend": "embedded", "status": "ok"},
    "objects":    {"backend": "filesystem", "status": "ok"},
    "cache":      {"backend": "memory", "status": "ok"},
    "relational": {"backend": "sqlite", "status": "ok"},
    "models":     {"status": "degraded", "detail": "no GPU"}
  }
}
```

### `GET /api/health/live`

Process liveness only — never touches a dependency. Returns `{"status": "alive"}`.

### `GET /api/metrics`

Counters and latency histograms: request counts by route, model latency by role,
retrieval/rerank latency, ingest job counts by status, GPU memory samples.
`Accept: text/plain` returns a Prometheus exposition; JSON otherwise.

### `GET /api/models`

Returns `ModelRuntimeStatus`: runtime profile, GPU availability, resident models, queue depth, 
degraded status.

### `POST /api/models/{role}/unload`

Force-evict a model role from memory (admin only). Returns `{status: "unloaded", role: "..."}`.

---

## 2. Search

### `POST /api/search`

Request = `SearchRequest`:

```json
{
  "query": "authentication failures",
  "mode": "fast|deep",
  "top_k": 20,
  "filters": {
    "source_ids": [],
    "modalities": ["document"],
    "occurred_after": null,
    "occurred_before": null
  },
  "rerank": true
}
```

Response = `SearchResponse`:

```json
{
  "query": "...",
  "mode": "fast",
  "total_candidates": 184,
  "latency_ms": 142.3,
  "degraded": false,
  "degraded_reasons": [],
  "entities": ["ent_transaction_ab12"],
  "stages": [
    {
      "stage": "candidate_generation",
      "candidates_in": 0,
      "candidates_out": 184,
      "latency_ms": 31.2
    }
  ],
  "hits": [
    {
      "chunk_id": "chk_...",
      "asset_id": "ast_...",
      "source_id": "src_docs",
      "modality": "document",
      "title": "Incident_Report.pdf",
      "snippet": "...«authentication» timeout...",
      "score": 0.87,
      "scores": {
        "lexical": 0.7,
        "semantic": 0.8,
        "rerank": 0.9,
        "entity_match": 1.0,
        "metadata_match": 0.2,
        "source_reliability": 0.75,
        "freshness": 0.6,
        "final": 0.87
      },
      "provenance": {
        "source_id": "src_docs",
        "source_name": "Corporate Documents",
        "modality": "document",
        "object_uri": "spectra://objects/ab/abc123.pdf",
        "locator": {
          "kind": "document",
          "document_id": "DOC9182",
          "page": 14,
          "section": "Authentication"
        },
        "version_status": "approved",
        "created_at": "2026-03-11T10:42:01Z"
      },
      "entities": ["ent_..."],
      "occurred_at": "2026-03-11T10:42:01Z"
    }
  ]
}
```

#### Search behaviour

**The core behaviour change: search can return nothing.** Every ranking signal is min-max
normalised across the result set, so the best candidate always scores 1.0 on its strongest signal
however poor it was absolutely. Before this fix, a query for a name absent from the corpus
returned five confident-looking hits.

An *admissibility gate* now reads the raw signals before normalisation and drops anything with no
actual evidence. A candidate is admitted if it:

- Carries an exact enterprise-id match, or
- Carries any entity match, or
- Shares lexical overlap with the query, or
- Scores ≥0.35 on the cross-encoder (paraphrase match)

Cosine similarity (dense vector match) is deliberately *not* a gate — measured on this corpus an
exact match scored 0.35–0.47 semantic while an absent query scored 0.30–0.42, so it cannot
separate a match from noise. See `services/query/search/spectra_search/scoring.py` for the
measured table and the `has_evidence()` function.

### `POST /api/search/document`, `/api/search/video`, `/api/search/audio`

Modality-scoped variants. Same request body, forces `filters.modalities` to the specified
modality.

### `POST /api/search/image`

Image-driven search (multipart form).

**Request:** `file=<binary>` or JSON `{"image_asset_id": "..."}`

**Response:** `{search: SearchResponse, understanding: {ocr_text: "...", detected_entities: [...], caption: "..."}}`

If the image is not already in the corpus, it is ingested synchronously (OCR, captioning,
embedding happen on the ingestion path, never at query time). Then the entire result set is
searched against it (semantic + entity matching + cross-modal linking).

---

## 3. Answer

### `POST /api/answer`

Ask a question, get a short answer grounded in the search results. The answer is synthesised
from the top-k retrieved hits using a generative model, and every sentence must carry a citation
to a hit. Uncited sentences are dropped; if nothing survives the answer is dropped.

Request = `AnswerRequest`:

```json
{
  "query": "did the transaction fail because of a timeout?",
  "mode": "fast|deep",
  "top_k": 6,
  "source_ids": ["src_docs"]
}
```

`source_ids` restricts the search to those sources. An empty list - the default - means every
source the caller is permitted to read. The same filter is available on `POST /api/search` as
`filters.source_ids`.

Response = `AnswerResponse`:

```json
{
  "query": "did the transaction fail because of a timeout?",
  "answer": "The authentication service timed out at 02:03 [1]. No fraud rule fired [2].",
  "citations": [1, 2],
  "model": "ollama/qwen3",
  "degraded": false,
  "degraded_reason": null,
  "results": {
    "...full SearchResponse..."
  }
}
```

#### Answer behaviour

- **No hits, no answer.** If search returns no results, `answer` is empty.
- **No generative model, no answer.** If the model gateway is unavailable or degraded, `answer`
  is empty and `degraded_reason` explains why.
- **Nothing but the excerpts.** The model is given only the retrieved text and the question. It
  cannot access the corpus, the internet, or its own recollection. So `answer` is always
  grounded in the results, or absent.
- **Citations are mandatory.** Every sentence must cite a numbered hit `[N]`. Uncited sentences
  are dropped. If nothing is left, the whole answer is dropped and `degraded_reason` says
  `"the generated answer cited nothing that was retrieved"`.

The `results` field carries the full `SearchResponse` so the UI can show the evidence
independently of whether an answer was synthesised.

---

## 3a. Search history

Every completed search is recorded. Recording happens in a background task *after* the response
is assembled, so a slow or failing write can never delay a search or change its result - and
nothing here is ever read back into retrieval. The table can be truncated at any time without
affecting a single result.

### `GET /api/search/history`

Query parameters: `limit` (1-200, default 50). Most recent first.

```json
[
  {
    "search_id": "sh_0d57fb49e02d45cb",
    "query": "authentication timeout",
    "mode": "fast",
    "result_count": 7,
    "candidates_screened": 80,
    "latency_ms": 191.2,
    "source_ids": ["src_demo"],
    "answered": true,
    "user_id": "local-user",
    "searched_at": "2026-09-18T17:39:44.291720Z"
  }
]
```

A search that matched nothing is recorded with `result_count: 0`, not skipped - "I looked and
found nothing" is precisely the row worth keeping.

### `DELETE /api/search/history`

Requires `manage_sources`. Forgets every recorded search and returns `204`. Nothing indexed is
touched.

---

## 4. Uploads & assets

### `POST /api/uploads` (multipart)

Ingest a document, image, audio or video.

**Request:** `file=<binary>`, optional `source_id`.

**Response:** `202 Accepted` + `IngestJob`:

```json
{
  "job_id": "job_...",
  "asset_id": "ast_...",
  "source_id": "src_uploads",
  "status": "queued",
  "stage": "processing",
  "progress": 0.0,
  "message": null,
  "created_at": "2026-09-18T11:41:21.481129Z",
  "updated_at": "2026-09-18T11:41:21.481129Z",
  "error": null,
  "stages_completed": ["queued"]
}
```

Processing continues in the background; the client polls `/api/uploads/{job_id}` to watch
progress.

Rejections return `400/413` with `{error: "...", reason: "..."}` for: size over `MAX_UPLOAD_BYTES`,
disallowed media type, extension/MIME mismatch, antivirus hook failure.

### `GET /api/uploads/{job_id}`

Job progress. Status progresses through: `queued → processing → extracting → embedding → indexed → ready`
(or `failed` with `error`).

### `GET /api/uploads`

List recent uploads (limit 50 by default).

### `GET /api/assets/{asset_id}`

Asset metadata.

### `GET /api/assets/{asset_id}/content`

The bytes, `Content-Type` from the asset, supports HTTP `Range` (required for video seeking).
Never serves a path outside the object store.

### `GET /api/assets/{asset_id}/thumbnail`

JPEG poster frame for video, or page 1 render for documents.

### `GET /api/assets/{asset_id}/page/{page}`

Rendered document page as PNG.

### `GET /api/assets`

List assets (filter by `source_id`, `kind`; limit 100, offset 0).

---

## 5. Sources

### `GET /api/sources`

List all sources the caller has permission to read.

### `POST /api/sources`

Create a new source.

**Request:**

```json
{
  "name": "Customer Incidents DB",
  "type": "postgres",
  "connection": {"host": "postgres.local", "database": "incidents"},
  "secrets": {"password": "..."},
  "modalities": ["database"],
  "permissions": ["admin", "analyst", "viewer"]
}
```

Secrets go to the credential store, never to the descriptor. The response is `SourceDescriptor`
with a `credential_ref` if secrets were stored.

### `GET /api/sources/{source_id}`

Retrieve a source descriptor (no secrets included).

### `PATCH /api/sources/{source_id}`

Update a source: `{name, enabled, reliability_override, reliability_reason, permissions}`.

### `DELETE /api/sources/{source_id}`

Delete a source.

### `GET /api/sources/{source_id}/health`

Source health: connection status, row count for databases, file count for object stores.

### `POST /api/sources/{source_id}/sync`

Trigger incremental ingestion from the source (e.g. query a database for new rows, scan S3 for
new objects). Returns a report of discovered assets and queued jobs.

### `GET /api/sources/{source_id}/schema`

For structured data sources (SQL databases): tables, columns, primary keys, relationships.

---

## 6. Error envelope

```json
{
  "error": "<machine_code>",
  "reason": "<human readable>",
  "request_id": "req_...",
  "detail": {}
}
```

Status codes:

| Code | Meaning |
|------|---------|
| `400` | Validation failure or rejected request |
| `403` | Permission denied |
| `404` | Not found |
| `409` | Conflicting state |
| `413` | Payload too large |
| `422` | Schema violation |
| `429` | Budget or rate limit |
| `503` | Dependency unavailable (returns which one and whether a degraded path was used) |

---

## 7. Fixtures

The TypeScript frontend types are kept in sync with the Python models via fixtures at
`apps/frontend/src/lib/__fixtures__/*.json`. These are serialised from the live Pydantic
models; they are the ground truth for response shapes. Seven fixtures are maintained:

- `search-response.json`
- `model-runtime-status.json`
- `health-report.json`
- `source-descriptor.json`
- `source-health.json`
- `asset.json`
- `ingest-job.json`

See `scripts/emit_frontend_fixtures.py` for the fixture definitions. Run it to regenerate
fixtures after changing Pydantic models.
