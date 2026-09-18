/**
 * Contract tests: the frontend's Zod schemas against the backend's real shapes.
 *
 * The fixtures in `__fixtures__/` are serialised from the live pydantic models
 * by `scripts/emit_frontend_fixtures.py`, so these tests fail the moment the
 * Python contract and the TypeScript contract drift apart - which is the whole
 * point of having both.
 */
import { describe, expect, it } from 'vitest';

import { buildUrl } from './api';

import asset from './__fixtures__/asset.json';
import healthReport from './__fixtures__/health-report.json';
import ingestJob from './__fixtures__/ingest-job.json';
import modelRuntimeStatus from './__fixtures__/model-runtime-status.json';
import searchResponse from './__fixtures__/search-response.json';
import sourceDescriptor from './__fixtures__/source-descriptor.json';
import sourceHealth from './__fixtures__/source-health.json';
import { answerResponseSchema, searchResponseSchema } from './schemas/search';
import {
  assetSchema,
  healthReportSchema,
  ingestJobSchema,
  modelRuntimeStatusSchema,
  sourceDescriptorSchema,
  sourceHealthSchema,
} from './schemas/system';

/** An answer payload is assembled here because it wraps a real search response. */
const answerPayload = {
  query: 'why did the payment fail',
  answer: 'The authorisation call timed out [1]. No fraud rule fired [2].',
  citations: [1, 2],
  model: 'qwen3:30b-a3b',
  degraded: false,
  degraded_reason: null,
  results: searchResponse,
};

describe('API contract', () => {
  it('parses a search response', () => {
    const parsed = searchResponseSchema.parse(searchResponse);
    expect(parsed.hits.length).toBeGreaterThan(0);
    expect(parsed.total_candidates).toBeGreaterThan(0);
  });

  it('keeps document provenance precise enough to reopen the source', () => {
    const parsed = searchResponseSchema.parse(searchResponse);
    const document = parsed.hits.find((hit) => hit.modality === 'document');
    expect(document).toBeTruthy();
    const locator = document?.provenance.locator as Record<string, unknown>;
    expect(locator.document_id).toBeTruthy();
    expect(typeof locator.page).toBe('number');
  });

  it('keeps video provenance seekable', () => {
    const parsed = searchResponseSchema.parse(searchResponse);
    const video = parsed.hits.find((hit) => hit.modality === 'video');
    if (!video) return;
    const locator = video.provenance.locator as Record<string, unknown>;
    expect(typeof locator.start_seconds).toBe('number');
  });

  it('carries a score breakdown for every hit, never a bare number', () => {
    const parsed = searchResponseSchema.parse(searchResponse);
    for (const hit of parsed.hits) {
      expect(hit.scores).toBeTruthy();
      expect(typeof hit.scores.final).toBe('number');
    }
  });

  it('parses an answer and the results it was written from', () => {
    const parsed = answerResponseSchema.parse(answerPayload);
    expect(parsed.answer).toContain('[1]');
    expect(parsed.citations).toEqual([1, 2]);
    expect(parsed.results.hits.length).toBeGreaterThan(0);
  });

  it('accepts an empty answer, because saying nothing is a real outcome', () => {
    const parsed = answerResponseSchema.parse({
      ...answerPayload,
      answer: '',
      citations: [],
      degraded: true,
      degraded_reason: 'no generative runtime available',
    });
    expect(parsed.answer).toBe('');
    expect(parsed.degraded_reason).toBe('no generative runtime available');
  });

  it('accepts a search that matched nothing', () => {
    const parsed = searchResponseSchema.parse({
      ...searchResponse,
      hits: [],
      total_candidates: 80,
    });
    expect(parsed.hits).toHaveLength(0);
    expect(parsed.total_candidates).toBe(80);
  });

  it('drops the retired investigation contract rather than rendering it', () => {
    const parsed = answerResponseSchema.parse({
      ...answerPayload,
      claims: [{ claim_id: 'C1' }],
      contradictions: [{ contradiction_id: 'con_1' }],
      autopsy: { candidates_retrieved: 1 },
    });
    expect(parsed).not.toHaveProperty('claims');
    expect(parsed).not.toHaveProperty('contradictions');
    expect(parsed).not.toHaveProperty('autopsy');
  });

  it('parses model runtime status including an unavailable GPU', () => {
    const parsed = modelRuntimeStatusSchema.parse(modelRuntimeStatus);
    expect(parsed.models.length).toBeGreaterThan(0);
    expect(typeof parsed.gpu.available).toBe('boolean');
  });

  it('parses a degraded health report', () => {
    const parsed = healthReportSchema.parse(healthReport);
    expect(parsed.degraded).toBe(true);
    expect(parsed.status).toBe('degraded');
  });

  it('accepts a healthy component that reports no detail', () => {
    const parsed = healthReportSchema.parse(healthReport);
    expect(parsed.components.vectors).toBeTruthy();
  });

  it('reads backends from the top level, not from components', () => {
    const parsed = healthReportSchema.parse(healthReport);
    expect(parsed.backends.relational).toBe('sqlite');
    expect(parsed.components).not.toHaveProperty('backends');
  });

  it('parses sources, health, assets and jobs', () => {
    expect(sourceDescriptorSchema.array().parse(sourceDescriptor)).toHaveLength(1);
    expect(sourceHealthSchema.parse(sourceHealth).source_id).toBe('src_docs');
    expect(assetSchema.parse(asset).page_count).toBe(14);
    expect(ingestJobSchema.parse(ingestJob).progress).toBeCloseTo(0.6);
  });

  it('never silently accepts a malformed payload', () => {
    expect(() => searchResponseSchema.parse({ query: 'x' })).toThrow();
    expect(() => answerResponseSchema.parse({ query: 'x' })).toThrow();
  });
});

describe('URL building', () => {
  it('builds a root-relative URL in same-origin mode', () => {
    expect(buildUrl('/api/search')).toBe('/api/search');
  });

  it('appends query parameters and skips empty ones', () => {
    const url = buildUrl('/api/sources', { limit: 10, cursor: undefined });
    expect(url).toContain('limit=10');
    expect(url).not.toContain('cursor');
  });

  it('never throws for any documented route', () => {
    for (const path of ['/api/search', '/api/answer', '/api/health', '/api/sources', '/api/models']) {
      expect(() => buildUrl(path)).not.toThrow();
    }
  });
});
