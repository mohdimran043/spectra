-- ===========================================================================
-- SPECTRA control plane - greenfield baseline.
--
-- Target database: ${POSTGRES_DB} (default `spectra`).
-- Applied ONCE by scripts/run-migrations.sh when the database is empty.
-- Never edit this file to change a live deployment: add an ordered file under
-- db/migrations/ instead.
--
-- Shapes mirror services/storage/spectra_storage/repository.py and the pydantic
-- models in packages/schemas/spectra_schemas.  Structured pydantic fields are
-- stored as jsonb; closed vocabularies are enforced with CHECK constraints so
-- a bad enum value fails at the database rather than three layers later.
-- ===========================================================================

-- spectra:target=control

BEGIN;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---------------------------------------------------------------------------
-- sources: every configured place SPECTRA may read from.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sources (
    source_id            text PRIMARY KEY,
    name                 text        NOT NULL,
    type                 text        NOT NULL
        CHECK (type IN ('local_folder', 's3', 'postgres', 'mysql', 'sqlite', 'rest_api', 'upload')),
    modalities           jsonb       NOT NULL DEFAULT '[]'::jsonb,
    -- Connection details only.  Secrets live in the secret store, reached via
    -- credential_ref; never inline them here.
    connection           jsonb       NOT NULL DEFAULT '{}'::jsonb,
    credential_ref       text,
    enabled              boolean     NOT NULL DEFAULT true,
    reliability_override double precision
        CHECK (reliability_override IS NULL OR (reliability_override >= 0 AND reliability_override <= 1)),
    reliability_reason   text,
    permissions          jsonb       NOT NULL DEFAULT '["admin","analyst","viewer"]'::jsonb,
    created_at           timestamptz NOT NULL DEFAULT now(),
    last_sync            timestamptz,
    record_count         bigint      NOT NULL DEFAULT 0,
    asset_count          bigint      NOT NULL DEFAULT 0,
    status               text        NOT NULL DEFAULT 'unconfigured'
        CHECK (status IN ('healthy', 'degraded', 'unreachable', 'unconfigured')),
    status_detail        text
);

CREATE INDEX IF NOT EXISTS idx_sources_type    ON sources (type);
CREATE INDEX IF NOT EXISTS idx_sources_enabled ON sources (enabled) WHERE enabled;

-- ---------------------------------------------------------------------------
-- assets: one ingested object (file, image, video, audio, table export).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS assets (
    asset_id         text PRIMARY KEY,
    source_id        text        NOT NULL REFERENCES sources (source_id) ON DELETE CASCADE,
    kind             text        NOT NULL
        CHECK (kind IN ('document', 'image', 'video', 'audio', 'table')),
    title            text        NOT NULL,
    object_uri       text        NOT NULL,
    media_type       text        NOT NULL,
    size_bytes       bigint      NOT NULL DEFAULT 0,
    content_hash     text        NOT NULL DEFAULT '',
    version          text        NOT NULL DEFAULT '1',
    version_status   text        NOT NULL DEFAULT 'current'
        CHECK (version_status IN ('current', 'superseded', 'deleted')),
    created_at       timestamptz NOT NULL DEFAULT now(),
    modified_at      timestamptz,
    ingested_at      timestamptz,
    status           text        NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'processing', 'extracting', 'embedding', 'indexed', 'ready', 'failed')),
    error            text,
    metadata         jsonb       NOT NULL DEFAULT '{}'::jsonb,
    duration_seconds double precision,
    page_count       integer,
    permissions      jsonb       NOT NULL DEFAULT '["admin","analyst","viewer"]'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_assets_source   ON assets (source_id);
CREATE INDEX IF NOT EXISTS idx_assets_kind     ON assets (kind);
CREATE INDEX IF NOT EXISTS idx_assets_status   ON assets (status);
CREATE INDEX IF NOT EXISTS idx_assets_ingested ON assets (ingested_at DESC NULLS LAST);
-- Deduplication lookup (find_asset_by_hash).
CREATE INDEX IF NOT EXISTS idx_assets_hash     ON assets (content_hash) WHERE content_hash <> '';

-- ---------------------------------------------------------------------------
-- chunks: the atomic retrievable unit.  Documents, transcripts, OCR output,
-- scene descriptions and serialised rows all land here, which is what makes
-- cross-modal retrieval one code path instead of five.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id      text PRIMARY KEY,
    asset_id      text        NOT NULL REFERENCES assets (asset_id)   ON DELETE CASCADE,
    source_id     text        NOT NULL REFERENCES sources (source_id) ON DELETE CASCADE,
    modality      text        NOT NULL
        CHECK (modality IN ('document', 'image', 'video', 'audio', 'database', 'graph', 'external')),
    text          text        NOT NULL,
    title         text,
    ordinal       integer     NOT NULL DEFAULT 0,
    provenance    jsonb       NOT NULL DEFAULT '{}'::jsonb,
    entities      jsonb       NOT NULL DEFAULT '[]'::jsonb,
    metadata      jsonb       NOT NULL DEFAULT '{}'::jsonb,
    index_version text,
    embedding_ref text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    -- When the described event happened; drives the investigation timeline.
    occurred_at   timestamptz,
    permissions   jsonb       NOT NULL DEFAULT '["admin","analyst","viewer"]'::jsonb,
    -- Lexical fallback when the OpenSearch backend is unavailable.
    text_search   tsvector GENERATED ALWAYS AS
        (to_tsvector('english', coalesce(title, '') || ' ' || text)) STORED
);

CREATE INDEX IF NOT EXISTS idx_chunks_asset    ON chunks (asset_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_chunks_source   ON chunks (source_id);
CREATE INDEX IF NOT EXISTS idx_chunks_modality ON chunks (modality);
CREATE INDEX IF NOT EXISTS idx_chunks_version  ON chunks (index_version);
CREATE INDEX IF NOT EXISTS idx_chunks_occurred ON chunks (occurred_at) WHERE occurred_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_chunks_search   ON chunks USING gin (text_search);

-- ---------------------------------------------------------------------------
-- entities: the resolved identity many mentions collapse onto.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS entities (
    entity_id       text PRIMARY KEY,
    entity_type     text        NOT NULL
        CHECK (entity_type IN ('person', 'customer', 'transaction', 'incident', 'asset',
                               'service', 'organisation', 'location', 'event', 'other')),
    canonical_name  text        NOT NULL,
    aliases         jsonb       NOT NULL DEFAULT '[]'::jsonb,
    normalized_keys jsonb       NOT NULL DEFAULT '[]'::jsonb,
    confidence      double precision NOT NULL DEFAULT 1.0
        CHECK (confidence >= 0 AND confidence <= 1),
    source_ids      jsonb       NOT NULL DEFAULT '[]'::jsonb,
    modalities      jsonb       NOT NULL DEFAULT '[]'::jsonb,
    attributes      jsonb       NOT NULL DEFAULT '{}'::jsonb,
    mention_count   integer     NOT NULL DEFAULT 0,
    first_seen      timestamptz NOT NULL DEFAULT now(),
    last_seen       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_entities_type ON entities (entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities (lower(canonical_name));
-- find_entities_by_key: exact containment lookup over the normalized keys.
CREATE INDEX IF NOT EXISTS idx_entities_keys ON entities USING gin (normalized_keys jsonb_path_ops);
-- search_entities: fuzzy surface matching.
CREATE INDEX IF NOT EXISTS idx_entities_trgm ON entities USING gin (canonical_name gin_trgm_ops);

-- ---------------------------------------------------------------------------
-- entity_links: the `chunk REFERS_TO entity` edge produced during ingestion.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS entity_links (
    entity_id  text NOT NULL REFERENCES entities (entity_id) ON DELETE CASCADE,
    chunk_id   text NOT NULL REFERENCES chunks   (chunk_id)  ON DELETE CASCADE,
    asset_id   text NOT NULL,
    source_id  text NOT NULL,
    modality   text NOT NULL
        CHECK (modality IN ('document', 'image', 'video', 'audio', 'database', 'graph', 'external')),
    surface    text NOT NULL,
    confidence double precision NOT NULL DEFAULT 1.0
        CHECK (confidence >= 0 AND confidence <= 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (entity_id, chunk_id)
);

CREATE INDEX IF NOT EXISTS idx_entity_links_chunk  ON entity_links (chunk_id);
CREATE INDEX IF NOT EXISTS idx_entity_links_asset  ON entity_links (asset_id);
CREATE INDEX IF NOT EXISTS idx_entity_links_entity ON entity_links (entity_id, confidence DESC);

-- ---------------------------------------------------------------------------
-- ingest_jobs: pipeline progress surfaced in the UI.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ingest_jobs (
    job_id           text PRIMARY KEY,
    asset_id         text        REFERENCES assets  (asset_id)  ON DELETE SET NULL,
    source_id        text        NOT NULL REFERENCES sources (source_id) ON DELETE CASCADE,
    status           text        NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'processing', 'extracting', 'embedding', 'indexed', 'ready', 'failed')),
    stage            text        NOT NULL DEFAULT 'queued',
    progress         double precision NOT NULL DEFAULT 0.0
        CHECK (progress >= 0 AND progress <= 1),
    message          text,
    error            text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    stages_completed jsonb       NOT NULL DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_jobs_status  ON ingest_jobs (status);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON ingest_jobs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_asset   ON ingest_jobs (asset_id);

-- ---------------------------------------------------------------------------
-- investigation_cases: a persistent case that can be reopened and continued.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS investigation_cases (
    case_id             text PRIMARY KEY,
    title               text        NOT NULL,
    question            text        NOT NULL,
    investigation_ids   jsonb       NOT NULL DEFAULT '[]'::jsonb,
    entity_ids          jsonb       NOT NULL DEFAULT '[]'::jsonb,
    status              text        NOT NULL DEFAULT 'created'
        CHECK (status IN ('created', 'running', 'awaiting_input', 'completed', 'failed')),
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    evidence_count      integer     NOT NULL DEFAULT 0,
    contradiction_count integer     NOT NULL DEFAULT 0,
    hypothesis_count    integer     NOT NULL DEFAULT 0,
    confidence          double precision NOT NULL DEFAULT 0.0
        CHECK (confidence >= 0 AND confidence <= 1)
);

CREATE INDEX IF NOT EXISTS idx_cases_status  ON investigation_cases (status);
CREATE INDEX IF NOT EXISTS idx_cases_updated ON investigation_cases (updated_at DESC);

-- ---------------------------------------------------------------------------
-- investigations: the agent's whole memory for one run.
-- Hot columns are promoted for listing and filtering; `state` holds the full
-- serialised InvestigationState so nothing is lost when the model gains fields.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS investigations (
    investigation_id text PRIMARY KEY,
    case_id          text        REFERENCES investigation_cases (case_id) ON DELETE SET NULL,
    goal             text        NOT NULL,
    mode             text        NOT NULL DEFAULT 'deep' CHECK (mode IN ('fast', 'deep')),
    status           text        NOT NULL DEFAULT 'created'
        CHECK (status IN ('created', 'running', 'awaiting_input', 'completed', 'failed')),
    answer           text        NOT NULL DEFAULT '',
    answer_status    text        NOT NULL DEFAULT 'insufficient_evidence'
        CHECK (answer_status IN ('supported', 'partially_supported', 'contested',
                                 'insufficient_evidence', 'degraded', 'failed')),
    confidence       double precision NOT NULL DEFAULT 0.0
        CHECK (confidence >= 0 AND confidence <= 1),
    degraded         boolean     NOT NULL DEFAULT false,
    degraded_reasons jsonb       NOT NULL DEFAULT '[]'::jsonb,
    user_id          text,
    role             text        NOT NULL DEFAULT 'analyst'
        CHECK (role IN ('admin', 'analyst', 'viewer')),
    state            jsonb       NOT NULL DEFAULT '{}'::jsonb,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_investigations_case    ON investigations (case_id);
CREATE INDEX IF NOT EXISTS idx_investigations_status  ON investigations (status);
CREATE INDEX IF NOT EXISTS idx_investigations_created ON investigations (created_at DESC);

-- ---------------------------------------------------------------------------
-- trace_steps: observable actions only.  Never model chain-of-thought.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trace_steps (
    step_id          text PRIMARY KEY,
    investigation_id text        NOT NULL REFERENCES investigations (investigation_id) ON DELETE CASCADE,
    sequence         integer     NOT NULL,
    agent            text        NOT NULL,
    tool             text,
    status           text        NOT NULL DEFAULT 'started'
        CHECK (status IN ('started', 'ok', 'empty', 'skipped', 'degraded', 'error')),
    title            text        NOT NULL DEFAULT '',
    input_summary    text        NOT NULL DEFAULT '',
    output_summary   text        NOT NULL DEFAULT '',
    started_at       timestamptz NOT NULL DEFAULT now(),
    completed_at     timestamptz,
    latency_ms       double precision NOT NULL DEFAULT 0.0,
    evidence_ids     jsonb       NOT NULL DEFAULT '[]'::jsonb,
    error            text,
    metadata         jsonb       NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (investigation_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_trace_investigation ON trace_steps (investigation_id, sequence);
CREATE INDEX IF NOT EXISTS idx_trace_agent         ON trace_steps (agent);

-- ---------------------------------------------------------------------------
-- index_versions: models change without destroying the index.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS index_versions (
    index_version       text PRIMARY KEY,
    embedding_model     text        NOT NULL,
    embedding_dimension integer     NOT NULL CHECK (embedding_dimension > 0),
    parser_version      text        NOT NULL,
    vision_model        text,
    speech_model        text,
    ocr_engine          text,
    is_active           boolean     NOT NULL DEFAULT false,
    created_at          timestamptz NOT NULL DEFAULT now()
);

-- At most one active index version at a time.
CREATE UNIQUE INDEX IF NOT EXISTS idx_index_versions_active
    ON index_versions ((is_active)) WHERE is_active;

-- ---------------------------------------------------------------------------
-- sql_audit: every statement the Database Agent ran, successful or not.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sql_audit (
    audit_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id  text        NOT NULL,
    sql        text        NOT NULL,
    params     jsonb       NOT NULL DEFAULT '{}'::jsonb,
    user_id    text        NOT NULL DEFAULT 'unknown',
    rows       integer     NOT NULL DEFAULT 0,
    ok         boolean     NOT NULL DEFAULT true,
    error      text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sql_audit_created ON sql_audit (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sql_audit_source  ON sql_audit (source_id);
CREATE INDEX IF NOT EXISTS idx_sql_audit_failed  ON sql_audit (created_at DESC) WHERE NOT ok;

COMMIT;
