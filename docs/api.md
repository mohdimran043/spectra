# SPECTRA API Contract

Base URL: `http://localhost:8000`. All payloads are JSON unless stated.
Every response carries `X-Request-ID`; investigation endpoints also echo `X-Investigation-ID`.

Authentication in development is a header-based role shim:

```
X-Spectra-User: <user id>        # optional, defaults to "local-user"
X-Spectra-Role: admin|analyst|viewer   # defaults to DEFAULT_ROLE
```

This is deliberately a thin `PermissionContext` factory so OAuth/OIDC/Keycloak can replace it
without touching any tool or retrieval code.

---

## 1. Health & system

### `GET /api/health`
```json
{
  "status": "ok|degraded|error",
  "version": "1.0.0",
  "deployment_mode": "development",
  "degraded": false,
  "checked_at": "2026-09-17T10:00:00Z",
  "components": {
    "vectors":    {"backend": "embedded", "status": "ok"},
    "lexical":    {"backend": "embedded", "status": "ok"},
    "graph":      {"backend": "embedded", "status": "ok"},
    "objects":    {"backend": "filesystem", "status": "ok"},
    "cache":      {"backend": "memory", "status": "ok"},
    "relational": {"backend": "sqlite", "status": "ok"},
    "models":     {"status": "degraded", "detail": "no generative runtime"}
  }
}
```

### `GET /api/metrics`
Counters and latency histograms: request counts by route, model latency by role,
retrieval/rerank/graph latency, ingest job counts by status, GPU memory samples.
`Accept: text/plain` returns a Prometheus exposition; JSON otherwise.

### `GET /api/models`
`ModelRuntimeStatus`: `{profile, gpu:{available,name,total_mb,used_mb,free_mb,utilisation_pct,budget_mb,detail},
models:[ModelInfo], resident_roles, active_role, queue_depth, recent_events, degraded, degraded_reasons}`.

### `POST /api/models/{role}/unload` — force-evict a role (admin only).

### `GET /api/agents/status`
`[{name,label,enabled,ready,state,reason,depends_on,alternatives,tools}]` — powers the Agent Control Center.

### `PATCH /api/agents/{name}` — body `{"enabled": bool}` (admin). Runtime toggle, no restart.

---

## 2. Search

### `POST /api/search`
Request = `SearchRequest`:
```json
{"query":"authentication failures","mode":"fast|deep","top_k":20,
 "filters":{"source_ids":[],"modalities":["document"],"entity_ids":[],
            "occurred_after":null,"occurred_before":null,"media_types":[]},
 "image_asset_id":null,"include_text":false,"rerank":true}
```
Response = `SearchResponse`:
```json
{"query":"...","mode":"fast","total_candidates":184,"latency_ms":142.3,
 "degraded":false,"degraded_reasons":[],"entities":["ent_transaction_ab12"],
 "stages":[{"stage":"candidate_generation","candidates_in":0,"candidates_out":184,"latency_ms":31.2}],
 "hits":[{"chunk_id":"chk_...","asset_id":"ast_...","source_id":"src_docs",
          "modality":"document","title":"Incident_Report.pdf","snippet":"... «authentication» timeout ...",
          "score":0.87,
          "scores":{"lexical":0.7,"semantic":0.8,"rerank":0.9,"entity_match":1.0,
                    "metadata_match":0.2,"source_reliability":0.75,"freshness":0.6,"final":0.87},
          "provenance":{"source_id":"src_docs","modality":"document",
                        "object_uri":"spectra://objects/ab/abc123.pdf",
                        "locator":{"kind":"document","document_id":"DOC9182","page":14,"section":"Authentication"},
                        "version_status":"approved","created_at":"..."},
          "entities":["ent_..."],"occurred_at":"..."}]}
```

Modality-scoped variants take the same body and force the filter:
`POST /api/search/document`, `/api/search/image`, `/api/search/video`, `/api/search/audio`.

### `POST /api/search/image` (multipart alternative)
`file=<binary>` or JSON `{"image_asset_id": "..."}` — image→everything: OCR + entity extraction +
multimodal ANN + entity-driven cross-source lookup. Returns `SearchResponse` plus
`{"understanding":{"ocr_text":"...","detected_entities":[...],"caption":"..."}}`.

### `POST /api/database/query`
```json
{"source_id":"src_enterprise","question":"failed transactions for C82731","sql":null,"params":{}}
```
Returns `{"sql":"SELECT ... WHERE customer_id = :customer_id LIMIT 500","params":{...},
"columns":[...],"rows":[...],"row_count":7,"truncated":false,"latency_ms":8.1,
"application_links":[...]}`. `sql` is always returned for transparency ("View generated SQL").
Rejected SQL returns **400** with `{"error":"sql_rejected","reason":"only SELECT statements are permitted"}`.

---

## 3. Uploads & assets

### `POST /api/uploads` (multipart)
`file=<binary>`, optional `source_id`, `investigation_id`.
Returns `202` + `IngestJob`: `{job_id,asset_id,source_id,status:"queued",stage,progress,message}`.

Rejections return **400/413** with `{"error":"upload_rejected","reason":"..."}` for: size over
`MAX_UPLOAD_BYTES`, disallowed media type, extension/MIME mismatch, antivirus hook failure.

### `GET /api/uploads/{job_id}` — job progress through
`queued → processing → extracting → embedding → indexed → ready` (or `failed` with `error`).

### `GET /api/assets/{asset_id}` — `Asset` metadata.
### `GET /api/assets/{asset_id}/content` — the bytes, `Content-Type` from the asset, supports `Range`
(required for video seeking). Never serves a path outside the object store.
### `GET /api/assets/{asset_id}/thumbnail` — JPEG poster frame / page render.
### `GET /api/assets/{asset_id}/page/{page}` — rendered document page PNG.

---

## 4. Investigations

### `POST /api/investigations`
```json
{"question":"Investigate why this transaction failed and show me the supporting evidence.",
 "mode":"deep","asset_ids":["ast_..."],"case_id":null,"stream":true}
```
Returns `202` + `{"investigation_id":"inv_...","case_id":"case_...","status":"running","stream_url":"/api/stream/investigation/inv_..."}`.

### `GET /api/investigations/{id}` — `InvestigationAnswer` (the structured response contract):
```json
{"investigation_id": "inv_abc123",
 "answer": "Transaction TX82931 failed because the authentication service timed out [E1][E2].",
 "confidence": 0.94,
 "confidence_label": "high",
 "status": "supported",
 "entities": [{"entity_id": "ent_transaction_ab12", "entity_type": "transaction",
               "canonical_name": "TX82931", "aliases": ["Txn 82931"]}],
 "evidence": [{"evidence_id": "evd_1", "label": "E1", "kind": "database", "modality": "database",
               "summary": "The authentication service connection pool was exhausted at 10:42.",
               "excerpt": "...connection pool was exhausted at 10:42, so the charge failed.",
               "stance": "supporting", "relevance": 0.91, "reliability": 0.75, "weight": 0.6825,
               "reliability_reason": "Database record, names TX82931 explicitly, corroborated by 2 sources",
               "citation": "Document: DOC9182 | Page: 14 | Section: Authentication",
               "claim_ids": ["C1", "C2"],
               "entities": ["ent_transaction_ab12"],
               "provenance": {"source_id": "src_docs", "source_name": "Corporate Documents",
                              "modality": "document", "version": "2", "version_status": "approved",
                              "object_uri": "spectra://objects/ab/abc123.pdf",
                              "locator": {"kind": "document", "document_id": "DOC9182",
                                          "page": 14, "section": "Authentication"},
                              "index_version": "idx_0001", "created_at": "2026-03-11T10:42:01Z"},
               "occurred_at": "2026-03-11T10:42:01Z", "retrieved_by": "search_documents"}],
 "contradictions": [{"contradiction_id": "con_1", "entity_id": "ent_incident_1",
                     "statement": "INC1829 status is reported as both 'approved' and 'rejected'",
                     "evidence_a": "evd_2", "evidence_b": "evd_3", "kind": "value_conflict",
                     "detail": "The superseded draft says rejected; the approved v2 says approved.",
                     "resolution": "Resolved in favour of evd_2: approved beats superseded.",
                     "resolved_in_favour_of": "evd_2", "severity": 0.7}],
 "timeline": [{"event_id": "evt_1", "occurred_at": "2026-03-11T10:42:01Z",
               "label": "Transaction created", "modality": "database",
               "evidence_ids": ["evd_1"], "precision": "exact"}],
 "claims": [{"claim_id": "C1",
             "text": "The authentication service timed out, so TX82931 failed.",
             "confidence": 0.94, "status": "supported",
             "supporting_evidence": ["evd_1", "evd_2"], "contradicting_evidence": [],
             "disproof_probe": "A successful authentication call for TX82931 inside the failure window.",
             "disproof_searched": true, "verified": true,
             "verification_note": "Two independent sources; no unresolved contradiction.",
             "rationale": "The failure_reason field and the post-mortem agree."},
            {"claim_id": "C2", "text": "No fraud rule fired for TX82931.",
             "confidence": 0.58, "status": "weak",
             "supporting_evidence": ["evd_1"], "contradicting_evidence": [],
             "disproof_probe": "A fraud-service decision log showing a rule match for TX82931.",
             "disproof_searched": true, "verified": true,
             "verification_note": "One source only; no independent corroboration found.",
             "rationale": "Absence of a rule-match row in the only log that would carry one."}],
 "application_links": [{"entity_id": "ent_transaction_ab12", "entity_type": "transaction",
                        "label": "Open Transaction", "record_id": "TX82931",
                        "url": "http://localhost:3001/transactions/TX82931",
                        "verified_in_database": true}],
 "explanation": {"reasons": ["The query referenced a transaction ID, so Database Search was selected first."],
                 "sources_selected": ["src_enterprise", "src_docs"],
                 "sources_skipped": [{"source": "src_images", "reason": "vision agent disabled"}]},
 "autopsy": {"investigation_id": "inv_abc123",
             "sources_considered": ["src_enterprise", "src_docs", "src_media"],
             "candidates_retrieved": 184, "evidence_used": 3, "evidence_rejected": 29,
             "rejection_reasons": {"below relevance floor": 24, "permission denied": 5},
             "tool_calls": 18, "tool_breakdown": {"search_documents": 6, "query_database": 3},
             "contradictions": 1, "total_latency_ms": 8400.0,
             "stage_latency_ms": {"candidate_generation": 31.2, "rerank": 88.0},
             "models_used": ["ollama/qwen3:30b-a3b", "transformers/BAAI/bge-m3"],
             "gpu_peak_mb": null,
             "claims_made": 2, "claims_refuted": 0, "evidence_diversity": 0.95,
             "degraded": false, "degraded_reasons": []},
 "metrics": {"total_latency_ms": 8400.0, "tool_calls": 18, "iterations": 3,
             "candidates_retrieved": 184, "evidence_used": 3, "evidence_rejected": 29,
             "contradictions": 1, "claims_made": 2, "claims_refuted": 0,
             "model_latency_ms": {"deep_brain": 5270.0},
             "models_used": ["ollama/qwen3:30b-a3b"], "stage_latency_ms": {"rerank": 88.0},
             "gpu_peak_mb": null, "tokens": {"deep_brain": 512},
             "sources_considered": ["src_enterprise", "src_docs", "src_media"]},
 "degraded": false, "degraded_reasons": [], "followups": ["Who approved INC1829?"]}
```

Enumerations in that payload:

| Field | Values |
|---|---|
| `status` | `supported` · `partially_supported` · `contested` · `insufficient_evidence` · `degraded` · `failed` |
| `confidence_label` | `high` · `medium` · `low` · `insufficient` |
| `claims[].status` | `supported` · `weak` · `contradicted` · `refuted` · `insufficient` |
| `evidence[].stance` | `supporting` · `contradicting` · `neutral` |

Claim ids are `C1`, `C2`, … within one investigation. Each claim is scored on its own evidence, so
the confidences do not sum to anything in particular; `claims` is ordered by confidence and the
first live (non-`refuted`) entry is the leading claim the answer is built around. `evidence_ids` and
`confidence_label` on a claim are derived properties and are not serialised: the two evidence lists
and `confidence` carry the same information.

### `GET /api/investigations` — recent investigations (summary rows).
### `POST /api/investigations/{id}/continue` — `{"question":"...","stream":true}` resumes persisted state.
### `GET /api/investigations/{id}/trace` — `[TraceStep]` (full history, for replay).
### `GET /api/investigations/{id}/autopsy` — `SearchAutopsy`.
### `GET /api/investigations/{id}/graph` — `GraphView` for the investigation.
### `GET /api/investigations/{id}/export?format=json|markdown` — case report download.

### `GET /api/stream/investigation/{id}` — **Server-Sent Events**
```
event: trace
data: {"step_id":"...","sequence":3,"agent":"database_agent","tool":"query_database",
       "status":"ok","title":"Database Agent","input_summary":"transaction TX82931",
       "output_summary":"1 record found","latency_ms":12.4,"evidence_ids":["evd_..."]}

event: claims
data: {"claims":[...]}

event: evidence
data: {"evidence":[...]}

event: status
data: {"status":"running","iteration":2,"budget":{"tool_calls_used":7,"max_tool_calls":30}}

event: complete
data: {...InvestigationAnswer...}

event: error
data: {"error":"...","recoverable":false}
```
Heartbeat `: keep-alive` every 15 s. Client reconnects with `Last-Event-ID`.

---

## 5. Cases

`GET /api/cases`, `GET /api/cases/{id}`, `POST /api/cases/{id}/reopen`,
`POST /api/cases/{id}/evidence` (attach an uploaded asset as evidence).

---

## 6. Entities, evidence, graph

- `GET /api/entities/{id}` — `CanonicalEntity` + `cross_modal_links` (which documents / videos /
  images / database records reference it) + application links.
- `GET /api/entities?q=...&type=...` — entity search.
- `POST /api/entities/resolve` — `{"surface":"Txn 82931"}` → `EntityResolution` with the full
  candidate list, winning method and explanation.
- `GET /api/evidence/{id}` — a single `EvidenceItem` with its provenance resolved to an openable target.
- `GET /api/graph/{node_id}?depth=2&types=MENTIONS,REFERS_TO` — `GraphView`.

---

## 7. Sources

- `GET /api/sources` — `[SourceDescriptor]` (credentials never included).
- `POST /api/sources` — create; secrets go to the credential store, never to `connection`.
- `GET /api/sources/{id}` / `PATCH` / `DELETE`.
- `GET /api/sources/{id}/health` — `SourceHealth`.
- `POST /api/sources/{id}/sync` — trigger incremental ingestion; returns a job.
- `GET /api/sources/{id}/schema` — for SQL sources: tables, columns, relationships.

---

## 8. Demo & evaluation

- `GET /api/demo/scenarios` — the six guided scenarios with their seed queries and narration.
- `POST /api/demo/run/{scenario_id}` — executes the scenario, returns the investigation id + stream url.
- `POST /api/demo/seed` — (re)load the synthetic enterprise dataset.
- `GET /api/eval/benchmarks` / `POST /api/eval/run` — benchmark suites and baseline comparison
  (`bm25`, `vector_rag`, `multimodal_rag`, `agentic`, `spectra`).

---

## Error envelope

```json
{"error":"<machine_code>","reason":"<human readable>","request_id":"req_...","detail":{}}
```
`400` validation/rejection · `403` permission · `404` unknown id · `409` conflicting state ·
`413` payload too large · `422` schema violation · `429` budget/rate · `503` dependency unavailable
(always with which dependency and whether a degraded path was used).
