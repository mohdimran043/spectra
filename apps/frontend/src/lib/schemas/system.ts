import { z } from 'zod';

import {
  assetKindSchema,
  isoDateTimeSchema,
  jobStatusSchema,
  modalitySchema,
  modelRoleSchema,
  modelStateSchema,
  sourceStatusSchema,
  sourceTypeSchema,
} from './primitives';

/* --------------------------------------------------------------------------
 * Health
 * ----------------------------------------------------------------------- */

export const healthComponentSchema = z.object({
  backend: z.string().optional(),
  status: z.string(),
  detail: z.string().optional(),
});
export type HealthComponent = z.infer<typeof healthComponentSchema>;

export const healthReportSchema = z.object({
  status: z.string(),
  version: z.string().default('unknown'),
  deployment_mode: z.string().default('unknown'),
  degraded: z.boolean().default(false),
  checked_at: isoDateTimeSchema.optional(),
  components: z.record(healthComponentSchema).default({}),
});
export type HealthReport = z.infer<typeof healthReportSchema>;

/* --------------------------------------------------------------------------
 * Model runtime
 * ----------------------------------------------------------------------- */

export const gpuStatusSchema = z.object({
  available: z.boolean().default(false),
  name: z.string().nullable().default(null),
  driver_version: z.string().nullable().optional(),
  total_mb: z.number().default(0),
  used_mb: z.number().default(0),
  free_mb: z.number().default(0),
  utilisation_pct: z.number().nullable().default(null),
  temperature_c: z.number().nullable().optional(),
  budget_mb: z.number().default(0),
  detail: z.string().nullable().default(null),
});
export type GpuStatus = z.infer<typeof gpuStatusSchema>;

export const modelCandidateSchema = z.object({
  runtime: z.string(),
  model: z.string(),
  vram_mb: z.number().default(0),
  device: z.string().default('auto'),
  dimension: z.number().nullable().optional(),
  compute_type: z.string().nullable().optional(),
  available: z.boolean().nullable().optional(),
  unavailable_reason: z.string().nullable().optional(),
});
export type ModelCandidate = z.infer<typeof modelCandidateSchema>;

export const modelInfoSchema = z.object({
  role: modelRoleSchema,
  enabled: z.boolean().default(true),
  purpose: z.string().default(''),
  state: modelStateSchema.default('registered'),
  active_runtime: z.string().nullable().default(null),
  active_model: z.string().nullable().default(null),
  device: z.string().nullable().default(null),
  vram_mb: z.number().default(0),
  dimension: z.number().nullable().default(null),
  candidates: z.array(modelCandidateSchema).default([]),
  loaded_at: isoDateTimeSchema.nullable().optional(),
  last_used_at: isoDateTimeSchema.nullable().optional(),
  load_count: z.number().default(0),
  unload_count: z.number().default(0),
  call_count: z.number().default(0),
  error_count: z.number().default(0),
  total_latency_ms: z.number().default(0),
  last_error: z.string().nullable().default(null),
  degraded: z.boolean().default(false),
  degraded_reason: z.string().nullable().default(null),
});
export type ModelInfo = z.infer<typeof modelInfoSchema>;

export const modelEventSchema = z.object({
  at: isoDateTimeSchema,
  role: modelRoleSchema,
  event: z.string(),
  detail: z.string().default(''),
  vram_mb: z.number().default(0),
});
export type ModelEvent = z.infer<typeof modelEventSchema>;

export const modelRuntimeStatusSchema = z.object({
  profile: z.string(),
  gpu: gpuStatusSchema,
  models: z.array(modelInfoSchema).default([]),
  resident_roles: z.array(modelRoleSchema).default([]),
  queue_depth: z.number().default(0),
  active_role: modelRoleSchema.nullable().default(null),
  recent_events: z.array(modelEventSchema).default([]),
  degraded: z.boolean().default(false),
  degraded_reasons: z.array(z.string()).default([]),
});
export type ModelRuntimeStatus = z.infer<typeof modelRuntimeStatusSchema>;

/* --------------------------------------------------------------------------
 * Agents
 * ----------------------------------------------------------------------- */

export const agentStatusSchema = z.object({
  name: z.string(),
  label: z.string(),
  enabled: z.boolean(),
  ready: z.boolean(),
  state: z.string().default('ready'),
  reason: z.string().nullable().default(null),
  depends_on: z.array(z.string()).default([]),
  alternatives: z.array(z.string()).default([]),
  tools: z.array(z.string()).default([]),
});
export type AgentStatusRow = z.infer<typeof agentStatusSchema>;

/* --------------------------------------------------------------------------
 * Sources
 * ----------------------------------------------------------------------- */

export const sourceDescriptorSchema = z.object({
  source_id: z.string(),
  name: z.string(),
  type: sourceTypeSchema,
  modalities: z.array(modalitySchema).default([]),
  connection: z.record(z.unknown()).default({}),
  credential_ref: z.string().nullable().default(null),
  enabled: z.boolean().default(true),
  reliability_override: z.number().nullable().default(null),
  reliability_reason: z.string().nullable().default(null),
  permissions: z.array(z.string()).default([]),
  created_at: isoDateTimeSchema.optional(),
  last_sync: isoDateTimeSchema.nullable().default(null),
  record_count: z.number().default(0),
  asset_count: z.number().default(0),
  status: sourceStatusSchema.default('unconfigured'),
  status_detail: z.string().nullable().default(null),
});
export type SourceDescriptor = z.infer<typeof sourceDescriptorSchema>;

export const sourceHealthSchema = z.object({
  source_id: z.string(),
  status: sourceStatusSchema,
  detail: z.string().nullable().default(null),
  checked_at: isoDateTimeSchema.optional(),
  latency_ms: z.number().nullable().default(null),
  asset_count: z.number().default(0),
  record_count: z.number().default(0),
});
export type SourceHealth = z.infer<typeof sourceHealthSchema>;

/* --------------------------------------------------------------------------
 * Assets & ingestion
 * ----------------------------------------------------------------------- */

export const assetSchema = z.object({
  asset_id: z.string(),
  source_id: z.string(),
  kind: assetKindSchema,
  title: z.string(),
  object_uri: z.string(),
  media_type: z.string(),
  size_bytes: z.number().default(0),
  content_hash: z.string().default(''),
  version: z.string().default('1'),
  version_status: z.string().default('current'),
  created_at: isoDateTimeSchema.optional(),
  modified_at: isoDateTimeSchema.nullable().optional(),
  ingested_at: isoDateTimeSchema.nullable().optional(),
  status: jobStatusSchema.default('queued'),
  error: z.string().nullable().default(null),
  metadata: z.record(z.unknown()).default({}),
  duration_seconds: z.number().nullable().default(null),
  page_count: z.number().nullable().default(null),
  permissions: z.array(z.string()).default([]),
});
export type Asset = z.infer<typeof assetSchema>;

export const ingestJobSchema = z.object({
  job_id: z.string(),
  asset_id: z.string().nullable().default(null),
  source_id: z.string(),
  status: jobStatusSchema.default('queued'),
  stage: z.string().default('queued'),
  progress: z.number().default(0),
  message: z.string().nullable().default(null),
  error: z.string().nullable().default(null),
  created_at: isoDateTimeSchema.optional(),
  updated_at: isoDateTimeSchema.optional(),
  stages_completed: z.array(z.string()).default([]),
});
export type IngestJob = z.infer<typeof ingestJobSchema>;

/* --------------------------------------------------------------------------
 * Demo
 *
 * `GET /api/demo/scenarios` is documented as "the six guided scenarios with their
 * seed queries and narration" without a field list. Every field except the id is
 * optional here and the UI renders only what arrives.
 * ----------------------------------------------------------------------- */

export const demoScenarioSchema = z.object({
  scenario_id: z.string(),
  title: z.string().optional(),
  name: z.string().optional(),
  description: z.string().optional(),
  summary: z.string().optional(),
  question: z.string().optional(),
  seed_query: z.string().optional(),
  query: z.string().optional(),
  mode: z.string().optional(),
  narration: z.union([z.string(), z.array(z.string())]).optional(),
  steps: z.array(z.string()).optional(),
  expected: z.string().optional(),
  modalities: z.array(modalitySchema).optional(),
});
export type DemoScenario = z.infer<typeof demoScenarioSchema>;

export const demoRunResponseSchema = z.object({
  investigation_id: z.string(),
  case_id: z.string().nullable().optional(),
  status: z.string().optional(),
  stream_url: z.string(),
});
export type DemoRunResponse = z.infer<typeof demoRunResponseSchema>;
