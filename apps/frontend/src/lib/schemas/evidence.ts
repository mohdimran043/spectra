import { z } from 'zod';

import {
  confidenceLabelSchema,
  entityTypeSchema,
  evidenceKindSchema,
  evidenceStanceSchema,
  hypothesisStatusSchema,
  isoDateTimeSchema,
  modalitySchema,
  provenanceSchema,
} from './primitives';

export const evidenceItemSchema = z.object({
  evidence_id: z.string(),
  kind: evidenceKindSchema,
  modality: modalitySchema,
  summary: z.string().default(''),
  excerpt: z.string().default(''),
  provenance: provenanceSchema,
  stance: evidenceStanceSchema.default('neutral'),
  relevance: z.number().default(0),
  reliability: z.number().default(0.5),
  reliability_reason: z.string().default(''),
  /** Present on `GET /api/investigations/{id}`; the API renders `provenance.human()`. */
  citation: z.string().optional(),
  entities: z.array(z.string()).default([]),
  occurred_at: isoDateTimeSchema.nullable().optional(),
  retrieved_at: isoDateTimeSchema.optional(),
  retrieved_by: z.string().default(''),
  hypothesis_ids: z.array(z.string()).default([]),
});
export type EvidenceItem = z.infer<typeof evidenceItemSchema>;

export const hypothesisSchema = z.object({
  hypothesis_id: z.string(),
  description: z.string(),
  rationale: z.string().default(''),
  status: hypothesisStatusSchema.default('open'),
  confidence: z.number().default(0),
  prior: z.number().default(0.25),
  supporting_evidence: z.array(z.string()).default([]),
  contradicting_evidence: z.array(z.string()).default([]),
  disproof_probe: z.string().nullable().default(null),
  disproof_searched: z.boolean().default(false),
  verified: z.boolean().default(false),
  verification_note: z.string().default(''),
  predicted_signals: z.array(z.string()).default([]),
});
export type Hypothesis = z.infer<typeof hypothesisSchema>;

export const contradictionSchema = z.object({
  contradiction_id: z.string(),
  statement: z.string(),
  evidence_a: z.string(),
  evidence_b: z.string(),
  kind: z.string().default('value_conflict'),
  detail: z.string().default(''),
  resolution: z.string().nullable().default(null),
  resolved_in_favour_of: z.string().nullable().default(null),
  severity: z.number().default(0.5),
  entity_id: z.string().nullable().default(null),
});
export type Contradiction = z.infer<typeof contradictionSchema>;

export const timelineEventSchema = z.object({
  event_id: z.string(),
  occurred_at: isoDateTimeSchema,
  label: z.string(),
  detail: z.string().default(''),
  modality: modalitySchema,
  evidence_ids: z.array(z.string()).default([]),
  entity_ids: z.array(z.string()).default([]),
  source_id: z.string().nullable().default(null),
  precision: z.string().default('exact'),
});
export type TimelineEvent = z.infer<typeof timelineEventSchema>;

export const claimSchema = z.object({
  claim_id: z.string(),
  text: z.string(),
  confidence: z.number(),
  status: z.string().default('supported'),
  evidence_ids: z.array(z.string()).default([]),
});
export type Claim = z.infer<typeof claimSchema>;

export const applicationLinkSchema = z.object({
  entity_id: z.string(),
  entity_type: entityTypeSchema,
  label: z.string(),
  url: z.string(),
  record_id: z.string(),
  verified_in_database: z.boolean().default(false),
});
export type ApplicationLink = z.infer<typeof applicationLinkSchema>;

export const verificationResultSchema = z.object({
  claim: z.string(),
  supported: z.boolean(),
  confidence: z.number(),
  supporting_evidence: z.array(z.string()).default([]),
  contradicting_evidence: z.array(z.string()).default([]),
  diversity: z.number().default(0),
  note: z.string().default(''),
  checks: z.record(z.boolean()).default({}),
});
export type VerificationResult = z.infer<typeof verificationResultSchema>;

export const canonicalEntitySchema = z.object({
  entity_id: z.string(),
  entity_type: entityTypeSchema,
  canonical_name: z.string(),
  aliases: z.array(z.string()).default([]),
  normalized_keys: z.array(z.string()).default([]),
  confidence: z.number().default(1),
  source_ids: z.array(z.string()).default([]),
  modalities: z.array(modalitySchema).default([]),
  attributes: z.record(z.unknown()).default({}),
  mention_count: z.number().default(0),
  first_seen: isoDateTimeSchema.optional(),
  last_seen: isoDateTimeSchema.optional(),
});
export type CanonicalEntity = z.infer<typeof canonicalEntitySchema>;

export const resolutionCandidateSchema = z.object({
  entity_id: z.string(),
  canonical_name: z.string(),
  entity_type: entityTypeSchema,
  score: z.number(),
  method: z.string(),
  rationale: z.string().nullable().optional(),
});

export const entityResolutionSchema = z.object({
  query: z.string(),
  normalized: z.string(),
  resolved: canonicalEntitySchema.nullable().default(null),
  confidence: z.number().default(0),
  method: z.string().default('none'),
  candidates: z.array(resolutionCandidateSchema).default([]),
  needs_verification: z.boolean().default(false),
  explanation: z.string().default(''),
});
export type EntityResolution = z.infer<typeof entityResolutionSchema>;

/**
 * `GET /api/entities/{id}` adds `cross_modal_links` and `application_links` to the
 * canonical entity. `docs/api.md` names both but does not give their shape, so the
 * link rows are parsed permissively and every field is treated as optional.
 */
export const crossModalLinkSchema = z.object({
  modality: modalitySchema.optional(),
  asset_id: z.string().optional(),
  chunk_id: z.string().optional(),
  source_id: z.string().optional(),
  title: z.string().nullable().optional(),
  surface: z.string().optional(),
  confidence: z.number().optional(),
});
export type CrossModalLink = z.infer<typeof crossModalLinkSchema>;

export const entityDetailSchema = canonicalEntitySchema.extend({
  cross_modal_links: z.array(crossModalLinkSchema).default([]),
  application_links: z.array(applicationLinkSchema).default([]),
});
export type EntityDetail = z.infer<typeof entityDetailSchema>;

export const graphNodeSchema = z.object({
  node_id: z.string(),
  labels: z.array(z.string()).default([]),
  properties: z.record(z.unknown()).default({}),
});
export type GraphNodeData = z.infer<typeof graphNodeSchema>;

export const graphEdgeSchema = z.object({
  edge_id: z.string(),
  type: z.string(),
  start: z.string(),
  end: z.string(),
  properties: z.record(z.unknown()).default({}),
});
export type GraphEdgeData = z.infer<typeof graphEdgeSchema>;

export const graphViewSchema = z.object({
  nodes: z.array(graphNodeSchema).default([]),
  edges: z.array(graphEdgeSchema).default([]),
  truncated: z.boolean().default(false),
});
export type GraphView = z.infer<typeof graphViewSchema>;

export { confidenceLabelSchema };
