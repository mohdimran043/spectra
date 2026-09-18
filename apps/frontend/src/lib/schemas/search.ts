import { z } from 'zod';

import {
  isoDateTimeSchema,
  modalitySchema,
  provenanceSchema,
  scoreBreakdownSchema,
  searchModeSchema,
} from './primitives';
import { applicationLinkSchema } from './evidence';

export const searchFiltersSchema = z.object({
  source_ids: z.array(z.string()).default([]),
  modalities: z.array(modalitySchema).default([]),
  asset_ids: z.array(z.string()).default([]),
  entity_ids: z.array(z.string()).default([]),
  occurred_after: isoDateTimeSchema.nullable().default(null),
  occurred_before: isoDateTimeSchema.nullable().default(null),
  media_types: z.array(z.string()).default([]),
});
export type SearchFilters = z.infer<typeof searchFiltersSchema>;

export const searchRequestSchema = z.object({
  query: z.string().default(''),
  mode: searchModeSchema.default('fast'),
  filters: searchFiltersSchema.default({
    source_ids: [],
    modalities: [],
    asset_ids: [],
    entity_ids: [],
    occurred_after: null,
    occurred_before: null,
    media_types: [],
  }),
  top_k: z.number().int().default(20),
  image_asset_id: z.string().nullable().default(null),
  include_text: z.boolean().default(false),
  rerank: z.boolean().default(true),
});
export type SearchRequest = z.infer<typeof searchRequestSchema>;

export const searchHitSchema = z.object({
  chunk_id: z.string(),
  asset_id: z.string(),
  source_id: z.string(),
  modality: modalitySchema,
  title: z.string().nullable().default(null),
  snippet: z.string().default(''),
  text: z.string().default(''),
  score: z.number().default(0),
  scores: scoreBreakdownSchema,
  provenance: provenanceSchema,
  entities: z.array(z.string()).default([]),
  metadata: z.record(z.unknown()).default({}),
  occurred_at: isoDateTimeSchema.nullable().default(null),
});
export type SearchHit = z.infer<typeof searchHitSchema>;

export const retrievalStageStatSchema = z.object({
  stage: z.string(),
  candidates_in: z.number().default(0),
  candidates_out: z.number().default(0),
  latency_ms: z.number().default(0),
  detail: z.string().nullable().optional(),
});
export type RetrievalStageStat = z.infer<typeof retrievalStageStatSchema>;

/**
 * `POST /api/search/image` returns a `SearchResponse` *plus* an `understanding`
 * block. The block is optional on every other search route, so it lives on the
 * one response schema rather than forking it.
 */
export const imageUnderstandingSchema = z.object({
  ocr_text: z.string().default(''),
  detected_entities: z.array(z.unknown()).default([]),
  caption: z.string().default(''),
});
export type ImageUnderstanding = z.infer<typeof imageUnderstandingSchema>;

export const searchResponseSchema = z.object({
  query: z.string(),
  mode: searchModeSchema,
  hits: z.array(searchHitSchema).default([]),
  total_candidates: z.number().default(0),
  stages: z.array(retrievalStageStatSchema).default([]),
  latency_ms: z.number().default(0),
  degraded: z.boolean().default(false),
  degraded_reasons: z.array(z.string()).default([]),
  entities: z.array(z.string()).default([]),
  understanding: imageUnderstandingSchema.optional(),
});
export type SearchResponse = z.infer<typeof searchResponseSchema>;

export const databaseQueryRequestSchema = z.object({
  source_id: z.string(),
  question: z.string(),
  sql: z.string().nullable().default(null),
  params: z.record(z.unknown()).default({}),
});
export type DatabaseQueryRequest = z.infer<typeof databaseQueryRequestSchema>;

export const databaseQueryResponseSchema = z.object({
  sql: z.string(),
  params: z.record(z.unknown()).default({}),
  columns: z.array(z.string()).default([]),
  rows: z.array(z.record(z.unknown())).default([]),
  row_count: z.number().default(0),
  truncated: z.boolean().default(false),
  latency_ms: z.number().default(0),
  application_links: z.array(applicationLinkSchema).default([]),
});
export type DatabaseQueryResponse = z.infer<typeof databaseQueryResponseSchema>;
