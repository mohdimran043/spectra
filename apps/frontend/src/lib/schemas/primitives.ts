import { z } from 'zod';

/**
 * Closed vocabularies. These mirror `packages/schemas/spectra_schemas/enums.py`
 * exactly — the API contract is frozen, so parsing is strict on purpose. A value
 * outside these sets is a contract breach and must surface as one, not be coerced
 * into something that renders quietly.
 */
export const modalitySchema = z.enum([
  'document',
  'image',
  'video',
  'audio',
  'database',
  'graph',
  'external',
]);
export type Modality = z.infer<typeof modalitySchema>;

export const searchModeSchema = z.enum(['fast', 'deep']);
export type SearchMode = z.infer<typeof searchModeSchema>;

export const sourceTypeSchema = z.enum([
  'local_folder',
  's3',
  'postgres',
  'mysql',
  'sqlite',
  'rest_api',
  'upload',
]);
export type SourceType = z.infer<typeof sourceTypeSchema>;

export const sourceStatusSchema = z.enum(['healthy', 'degraded', 'unreachable', 'unconfigured']);
export type SourceStatus = z.infer<typeof sourceStatusSchema>;

export const assetKindSchema = z.enum(['document', 'image', 'video', 'audio', 'table']);
export type AssetKind = z.infer<typeof assetKindSchema>;

export const jobStatusSchema = z.enum([
  'queued',
  'processing',
  'extracting',
  'embedding',
  'indexed',
  'ready',
  'failed',
]);
export type JobStatus = z.infer<typeof jobStatusSchema>;

export const entityTypeSchema = z.enum([
  'person',
  'customer',
  'transaction',
  'incident',
  'asset',
  'service',
  'organisation',
  'location',
  'event',
  'other',
]);
export type EntityType = z.infer<typeof entityTypeSchema>;

export const evidenceKindSchema = z.enum([
  'document',
  'image',
  'video',
  'audio',
  'database',
  'application_record',
  'external_api',
  'graph',
]);
export type EvidenceKind = z.infer<typeof evidenceKindSchema>;

export const evidenceStanceSchema = z.enum(['supporting', 'contradicting', 'neutral']);
export type EvidenceStance = z.infer<typeof evidenceStanceSchema>;

/**
 * A claim's standing. Claims are judged one at a time against their own
 * evidence, so these values describe a single statement's footing and never a
 * position in a field of rivals.
 */
export const claimStatusSchema = z.enum([
  'supported',
  'weak',
  'contradicted',
  'refuted',
  'insufficient',
]);
export type ClaimStatus = z.infer<typeof claimStatusSchema>;

export const confidenceLabelSchema = z.enum(['high', 'medium', 'low', 'insufficient']);
export type ConfidenceLabel = z.infer<typeof confidenceLabelSchema>;

export const answerStatusSchema = z.enum([
  'supported',
  'partially_supported',
  'insufficient_evidence',
  'degraded',
  'failed',
]);
export type AnswerStatus = z.infer<typeof answerStatusSchema>;

export const investigationStatusSchema = z.enum([
  'created',
  'running',
  'awaiting_input',
  'completed',
  'failed',
]);
export type InvestigationStatus = z.infer<typeof investigationStatusSchema>;

export const traceStatusSchema = z.enum([
  'started',
  'ok',
  'empty',
  'skipped',
  'degraded',
  'error',
]);
export type TraceStatus = z.infer<typeof traceStatusSchema>;

export const agentNameSchema = z.enum([
  'brain',
  'document_agent',
  'vision_agent',
  'video_agent',
  'audio_agent',
  'database_agent',
  'graph_agent',
  'entity_resolver',
  'claim_builder',
  'disproof_agent',
  'verifier',
  'timeline_builder',
]);
export type AgentName = z.infer<typeof agentNameSchema>;

export const modelRoleSchema = z.enum([
  'fast_brain',
  'deep_brain',
  'vision',
  'embedding',
  'mm_embedding',
  'reranker',
  'speech',
  'ocr',
]);
export type ModelRole = z.infer<typeof modelRoleSchema>;

export const modelStateSchema = z.enum([
  'unavailable',
  'registered',
  'loading',
  'loaded',
  'unloading',
  'error',
]);
export type ModelState = z.infer<typeof modelStateSchema>;

export const roleSchema = z.enum(['admin', 'analyst', 'viewer']);
export type Role = z.infer<typeof roleSchema>;

export const queryIntentSchema = z.enum([
  'lookup_by_id',
  'structured_query',
  'semantic_search',
  'media_location',
  'investigation',
  'temporal',
  'comparison',
]);
export type QueryIntent = z.infer<typeof queryIntentSchema>;

/**
 * Timestamps stay strings end to end. The wire format is ISO-8601 and every
 * consumer either formats it or sorts it lexicographically, so rehydrating a
 * `Date` would only add a serialisation boundary between server and client.
 */
export const isoDateTimeSchema = z.string();

const bboxSchema = z.tuple([z.number(), z.number(), z.number(), z.number()]);

export const documentLocatorSchema = z.object({
  kind: z.literal('document'),
  document_id: z.string(),
  page: z.number().int().nullable().optional(),
  section: z.string().nullable().optional(),
  paragraph: z.number().int().nullable().optional(),
  char_start: z.number().int().nullable().optional(),
  char_end: z.number().int().nullable().optional(),
  bbox: bboxSchema.nullable().optional(),
});

export const imageLocatorSchema = z.object({
  kind: z.literal('image'),
  image_id: z.string(),
  region: bboxSchema.nullable().optional(),
});

export const videoLocatorSchema = z.object({
  kind: z.literal('video'),
  video_id: z.string(),
  scene_id: z.string().nullable().optional(),
  frame_id: z.string().nullable().optional(),
  start_seconds: z.number().nullable().optional(),
  end_seconds: z.number().nullable().optional(),
});

export const audioLocatorSchema = z.object({
  kind: z.literal('audio'),
  audio_id: z.string(),
  segment_id: z.string().nullable().optional(),
  start_seconds: z.number().nullable().optional(),
  end_seconds: z.number().nullable().optional(),
  speaker: z.string().nullable().optional(),
});

export const databaseLocatorSchema = z.object({
  kind: z.literal('database'),
  source_id: z.string(),
  table: z.string(),
  primary_key: z.string(),
  record_id: z.string(),
  column: z.string().nullable().optional(),
});

export const externalLocatorSchema = z.object({
  kind: z.literal('external'),
  source_id: z.string(),
  resource: z.string(),
  record_id: z.string().nullable().optional(),
});

export const locatorSchema = z.discriminatedUnion('kind', [
  documentLocatorSchema,
  imageLocatorSchema,
  videoLocatorSchema,
  audioLocatorSchema,
  databaseLocatorSchema,
  externalLocatorSchema,
]);
export type Locator = z.infer<typeof locatorSchema>;

export const provenanceSchema = z.object({
  source_id: z.string(),
  source_name: z.string().nullable().optional(),
  modality: modalitySchema,
  object_uri: z.string(),
  locator: locatorSchema,
  content_hash: z.string().nullable().optional(),
  version: z.string().nullable().optional(),
  version_status: z.string().default('unknown'),
  created_at: isoDateTimeSchema.nullable().optional(),
  modified_at: isoDateTimeSchema.nullable().optional(),
  ingested_at: isoDateTimeSchema.nullable().optional(),
  index_version: z.string().nullable().optional(),
});
export type Provenance = z.infer<typeof provenanceSchema>;

export const scoreBreakdownSchema = z.object({
  lexical: z.number().default(0),
  semantic: z.number().default(0),
  rerank: z.number().nullable().default(null),
  entity_match: z.number().default(0),
  metadata_match: z.number().default(0),
  source_reliability: z.number().default(0.5),
  freshness: z.number().default(0.5),
  final: z.number().default(0),
});
export type ScoreBreakdown = z.infer<typeof scoreBreakdownSchema>;

/** The error envelope every non-2xx response carries. */
export const apiErrorEnvelopeSchema = z.object({
  error: z.string(),
  reason: z.string(),
  request_id: z.string().optional(),
  detail: z.record(z.unknown()).optional(),
});
export type ApiErrorEnvelope = z.infer<typeof apiErrorEnvelopeSchema>;
