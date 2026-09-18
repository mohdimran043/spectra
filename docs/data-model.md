# Data Model

## Identifier scheme

All ids are prefixed and, where possible, content-addressed so re-ingestion is idempotent.

| Id | Form | Derivation |
|---|---|---|
| `source_id` | `src_*` | assigned at registration |
| `asset_id` | `ast_<16 hex>` | `sha256(source_id, content_sha)` |
| `chunk_id` | `chk_<16 hex>` | `sha256(asset_id, ordinal, discriminator)` |
| `entity_id` | `ent_<type>_<12 hex>` | `sha256(entity_type, normalized_key)` |
| `evidence_id` | `evd_<14 hex>` | `sha256(chunk_or_record, claim_scope)` |
| `investigation_id` | `inv_<16 hex>` | random |
| `object_uri` | `spectra://objects/<aa>/<sha256>.<ext>` | content hash |

Nothing anywhere stores a filesystem path as a reference.

## Control plane (relational: SQLite or PostgreSQL)

```
sources(source_id PK, name, type, modalities, connection, credential_ref, enabled,
        reliability_override, reliability_reason, permissions, created_at, last_sync,
        record_count, asset_count, status, status_detail)

assets(asset_id PK, source_id FK, kind, title, object_uri, media_type, size_bytes,
       content_hash IDX, version, version_status, created_at, modified_at, ingested_at,
       status, error, metadata, duration_seconds, page_count, permissions)

chunks(chunk_id PK, asset_id FK IDX, source_id IDX, modality IDX, text, title, ordinal,
       provenance JSON, entities JSON, metadata JSON, index_version IDX, embedding_ref,
       created_at, occurred_at IDX, permissions)

entities(entity_id PK, entity_type IDX, canonical_name, aliases JSON, normalized_keys JSON IDX,
         confidence, source_ids JSON, modalities JSON, attributes JSON, mention_count,
         first_seen, last_seen)

entity_links(entity_id IDX, chunk_id IDX, asset_id, source_id, modality, surface, confidence)

ingest_jobs(job_id PK, asset_id, source_id, status, stage, progress, message, error,
            created_at, updated_at, stages_completed)

investigations(investigation_id PK, case_id IDX, goal, mode, status, state JSON,
               confidence, created_at, updated_at, user_id, role)

investigation_cases(case_id PK, title, question, investigation_ids JSON, entity_ids JSON,
                    status, created_at, updated_at, evidence_count, contradiction_count,
                    claim_count, confidence)

trace_steps(step_id PK, investigation_id IDX, sequence, agent, tool, status, title,
            input_summary, output_summary, started_at, completed_at, latency_ms,
            evidence_ids JSON, error, metadata)

index_versions(index_version PK, embedding_model, embedding_dimension, parser_version,
               vision_model, speech_model, ocr_engine, created_at)

sql_audit(id PK, source_id, sql, params JSON, user_id, rows, ok, error, created_at)
```

## Enterprise demo database (separate, reached through the connector)

Deliberately a *different* database, so "query a real structured source" is a genuine external-source
path and not a privileged internal shortcut. The mock enterprise application reads the same tables.

```
customers(customer_id PK, name, email, segment, country, risk_score, created_at, status)
transactions(transaction_id PK, customer_id FK, amount, currency, status, method,
             failure_reason, created_at, updated_at, incident_id FK)
incidents(incident_id PK, title, severity, status, category, root_cause, service,
          opened_at, resolved_at, approved, approved_by)
assets(asset_id PK, name, kind, owner, environment, service, status, created_at)
```

Accessed as `spectra_readonly`, a role granted `SELECT` only.

## Vector store

Two collections, because text and image embeddings have different dimensions and different models.

| Collection | Contents | Payload used for filtering |
|---|---|---|
| `spectra_text` | chunk embeddings (documents, transcripts, OCR, rows) | source_id, asset_id, modality, entities, permissions, occurred_at, index_version |
| `spectra_image` | image + keyframe embeddings in the multimodal space | same |

## Lexical index

`spectra_lexical` — one document per chunk with `text`, `title` and the same filter payload. The
tokeniser preserves alphanumeric identifiers intact.

## Evidence graph

**Node labels (17):** Person · Customer · Transaction · Incident · Event · Document · Page · Image ·
Video · Scene · Frame · Audio · AudioSegment · DatabaseRecord · ApplicationRecord · Claim · Evidence

**Relationship types (12):** MENTIONS · REFERS_TO · SAME_ENTITY · SUPPORTS · CONTRADICTS ·
CAUSED_BY · PRECEDES · SUPERSEDES · DERIVED_FROM · BELONGS_TO · EVIDENCE_FOR · OPENED_AS

Both sets are validated allowlists. Built **incrementally** during ingestion and investigation —
never as a batch rebuild.

Typical cross-modal shape:

```
(Document)-[:MENTIONS]->(Transaction)<-[:REFERS_TO]-(Scene)-[:BELONGS_TO]->(Video)
(DatabaseRecord)-[:IS]->(Transaction)-[:CAUSED_BY]->(Incident)
(Evidence)-[:SUPPORTS|CONTRADICTS|EVIDENCE_FOR]->(Claim)
```

## Index versioning

Every chunk carries an `index_version` naming the embedding model, dimension, parser version and the
vision/speech/OCR engines used. Changing a model writes a **new** index version alongside the live
one; `make reindex` migrates and the old version can serve until the migration completes. Cache keys
include the embedding identity so nothing stale survives.
