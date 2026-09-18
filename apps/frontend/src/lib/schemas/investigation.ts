import { z } from 'zod';

import {
  agentNameSchema,
  answerStatusSchema,
  confidenceLabelSchema,
  investigationStatusSchema,
  isoDateTimeSchema,
  searchModeSchema,
  traceStatusSchema,
} from './primitives';
import {
  applicationLinkSchema,
  canonicalEntitySchema,
  claimSchema,
  contradictionSchema,
  evidenceItemSchema,
  timelineEventSchema,
} from './evidence';

export const traceStepSchema = z.object({
  step_id: z.string(),
  /** Absent on SSE `trace` frames, present on `GET /api/investigations/{id}/trace`. */
  investigation_id: z.string().optional(),
  sequence: z.number().int(),
  agent: agentNameSchema,
  tool: z.string().nullable().default(null),
  status: traceStatusSchema.default('started'),
  title: z.string().default(''),
  input_summary: z.string().default(''),
  output_summary: z.string().default(''),
  started_at: isoDateTimeSchema.optional(),
  completed_at: isoDateTimeSchema.nullable().optional(),
  latency_ms: z.number().default(0),
  evidence_ids: z.array(z.string()).default([]),
  error: z.string().nullable().default(null),
  metadata: z.record(z.unknown()).default({}),
});
export type TraceStep = z.infer<typeof traceStepSchema>;

export const budgetStateSchema = z.object({
  mode: searchModeSchema.optional(),
  max_tool_calls: z.number().default(30),
  max_latency_seconds: z.number().optional(),
  max_iterations: z.number().optional(),
  tool_calls_used: z.number().default(0),
  iterations_used: z.number().optional(),
  elapsed_seconds: z.number().optional(),
  exhausted_reason: z.string().nullable().optional(),
});
export type BudgetState = z.infer<typeof budgetStateSchema>;

export const investigationMetricsSchema = z.object({
  total_latency_ms: z.number().default(0),
  tool_calls: z.number().default(0),
  iterations: z.number().default(0),
  candidates_retrieved: z.number().default(0),
  evidence_used: z.number().default(0),
  evidence_rejected: z.number().default(0),
  contradictions: z.number().default(0),
  claims_made: z.number().default(0),
  claims_refuted: z.number().default(0),
  model_latency_ms: z.record(z.number()).default({}),
  models_used: z.array(z.string()).default([]),
  stage_latency_ms: z.record(z.number()).default({}),
  gpu_peak_mb: z.number().nullable().default(null),
  tokens: z.record(z.number()).default({}),
  sources_considered: z.array(z.string()).default([]),
});
export type InvestigationMetrics = z.infer<typeof investigationMetricsSchema>;

export const queryExplanationSchema = z.object({
  reasons: z.array(z.string()).default([]),
  sources_selected: z.array(z.string()).default([]),
  sources_skipped: z.array(z.record(z.string())).default([]),
});
export type QueryExplanation = z.infer<typeof queryExplanationSchema>;

export const searchAutopsySchema = z.object({
  investigation_id: z.string(),
  sources_considered: z.array(z.string()).default([]),
  candidates_retrieved: z.number().default(0),
  evidence_used: z.number().default(0),
  evidence_rejected: z.number().default(0),
  rejection_reasons: z.record(z.number()).default({}),
  tool_calls: z.number().default(0),
  tool_breakdown: z.record(z.number()).default({}),
  contradictions: z.number().default(0),
  total_latency_ms: z.number().default(0),
  stage_latency_ms: z.record(z.number()).default({}),
  models_used: z.array(z.string()).default([]),
  gpu_peak_mb: z.number().nullable().default(null),
  claims_made: z.number().default(0),
  claims_refuted: z.number().default(0),
  evidence_diversity: z.number().default(0),
  degraded: z.boolean().default(false),
  degraded_reasons: z.array(z.string()).default([]),
});
export type SearchAutopsy = z.infer<typeof searchAutopsySchema>;

/**
 * `InvestigationAnswer.entities` is typed `list[dict[str, Any]]` server-side and
 * documented as canonical-entity rows. It is parsed with the canonical shape but
 * tolerates partial rows, because the server type does not guarantee every field.
 */
const answerEntitySchema = canonicalEntitySchema.partial().extend({
  entity_id: z.string(),
  canonical_name: z.string().optional(),
});
export type AnswerEntity = z.infer<typeof answerEntitySchema>;

export const investigationAnswerSchema = z.object({
  investigation_id: z.string(),
  answer: z.string(),
  confidence: z.number(),
  confidence_label: confidenceLabelSchema,
  status: answerStatusSchema,
  entities: z.array(answerEntitySchema).default([]),
  evidence: z.array(evidenceItemSchema).default([]),
  contradictions: z.array(contradictionSchema).default([]),
  timeline: z.array(timelineEventSchema).default([]),
  claims: z.array(claimSchema).default([]),
  application_links: z.array(applicationLinkSchema).default([]),
  explanation: queryExplanationSchema.default({
    reasons: [],
    sources_selected: [],
    sources_skipped: [],
  }),
  autopsy: searchAutopsySchema.nullable().default(null),
  metrics: investigationMetricsSchema.default({
    total_latency_ms: 0,
    tool_calls: 0,
    iterations: 0,
    candidates_retrieved: 0,
    evidence_used: 0,
    evidence_rejected: 0,
    contradictions: 0,
    claims_made: 0,
    claims_refuted: 0,
    model_latency_ms: {},
    models_used: [],
    stage_latency_ms: {},
    gpu_peak_mb: null,
    tokens: {},
    sources_considered: [],
  }),
  degraded: z.boolean().default(false),
  degraded_reasons: z.array(z.string()).default([]),
  followups: z.array(z.string()).default([]),
});
export type InvestigationAnswer = z.infer<typeof investigationAnswerSchema>;

export const createInvestigationResponseSchema = z.object({
  investigation_id: z.string(),
  case_id: z.string().nullable().default(null),
  status: z.string(),
  stream_url: z.string(),
});
export type CreateInvestigationResponse = z.infer<typeof createInvestigationResponseSchema>;

/**
 * `GET /api/investigations` is documented only as "recent investigations (summary
 * rows)". The row shape is not specified, so everything beyond the id is optional
 * and the UI degrades field by field rather than refusing the list.
 */
export const investigationSummarySchema = z.object({
  investigation_id: z.string(),
  case_id: z.string().nullable().optional(),
  question: z.string().optional(),
  goal: z.string().optional(),
  status: investigationStatusSchema.optional(),
  answer_status: answerStatusSchema.optional(),
  mode: searchModeSchema.optional(),
  confidence: z.number().optional(),
  confidence_label: confidenceLabelSchema.optional(),
  evidence_count: z.number().optional(),
  contradiction_count: z.number().optional(),
  created_at: isoDateTimeSchema.optional(),
  updated_at: isoDateTimeSchema.optional(),
});
export type InvestigationSummary = z.infer<typeof investigationSummarySchema>;

export const investigationCaseSchema = z.object({
  case_id: z.string(),
  title: z.string(),
  question: z.string(),
  investigation_ids: z.array(z.string()).default([]),
  entity_ids: z.array(z.string()).default([]),
  status: investigationStatusSchema.default('created'),
  created_at: isoDateTimeSchema.optional(),
  updated_at: isoDateTimeSchema.optional(),
  evidence_count: z.number().default(0),
  contradiction_count: z.number().default(0),
  claim_count: z.number().default(0),
  confidence: z.number().default(0),
});
export type InvestigationCase = z.infer<typeof investigationCaseSchema>;

/* --------------------------------------------------------------------------
 * SSE frames — `GET /api/stream/investigation/{id}`
 * ----------------------------------------------------------------------- */

export const streamClaimsFrameSchema = z.object({
  claims: z.array(claimSchema).default([]),
});

export const streamEvidenceFrameSchema = z.object({
  evidence: z.array(evidenceItemSchema).default([]),
});

export const streamStatusFrameSchema = z.object({
  status: z.string(),
  iteration: z.number().optional(),
  budget: budgetStateSchema.optional(),
});
export type StreamStatusFrame = z.infer<typeof streamStatusFrameSchema>;

export const streamErrorFrameSchema = z.object({
  error: z.string(),
  recoverable: z.boolean().default(false),
});
export type StreamErrorFrame = z.infer<typeof streamErrorFrameSchema>;
