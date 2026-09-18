/**
 * Contract tests: the frontend's Zod schemas against the backend's real shapes.
 *
 * The fixtures in `__fixtures__/` are serialised from the live pydantic models
 * by `scripts/emit_frontend_fixtures.py`, so these tests fail the moment the
 * Python contract and the TypeScript contract drift apart — which is the whole
 * point of having both.
 */
import { describe, expect, it } from 'vitest';

import agentStatus from './__fixtures__/agent-status.json';
import asset from './__fixtures__/asset.json';
import canonicalEntity from './__fixtures__/canonical-entity.json';
import graphView from './__fixtures__/graph-view.json';
import healthReport from './__fixtures__/health-report.json';
import ingestJob from './__fixtures__/ingest-job.json';
import investigationAnswer from './__fixtures__/investigation-answer.json';
import modelRuntimeStatus from './__fixtures__/model-runtime-status.json';
import searchResponse from './__fixtures__/search-response.json';
import sourceDescriptor from './__fixtures__/source-descriptor.json';
import sourceHealth from './__fixtures__/source-health.json';
import traceStep from './__fixtures__/trace-step.json';
import {
  agentStatusSchema,
  assetSchema,
  canonicalEntitySchema,
  graphViewSchema,
  healthReportSchema,
  ingestJobSchema,
  investigationAnswerSchema,
  modelRuntimeStatusSchema,
  searchResponseSchema,
  sourceDescriptorSchema,
  sourceHealthSchema,
  traceStepSchema,
} from './schemas';

describe('API contract', () => {
  it('parses a search response', () => {
    const parsed = searchResponseSchema.parse(searchResponse);
    expect(parsed.hits).toHaveLength(2);
    expect(parsed.hits[0]?.scores.final).toBeGreaterThan(0);
    expect(parsed.stages.length).toBeGreaterThan(0);
  });

  it('keeps document provenance precise enough to reopen the source', () => {
    const parsed = searchResponseSchema.parse(searchResponse);
    const locator = parsed.hits[0]?.provenance.locator;
    expect(locator).toBeDefined();
    expect(locator?.kind).toBe('document');
    if (locator?.kind === 'document') {
      expect(locator.page).toBe(14);
      expect(locator.section).toBe('Authentication');
    }
  });

  it('keeps video provenance seekable', () => {
    const parsed = searchResponseSchema.parse(searchResponse);
    const locator = parsed.hits[1]?.provenance.locator;
    expect(locator).toBeDefined();
    expect(locator?.kind).toBe('video');
    if (locator?.kind === 'video') {
      expect(locator.start_seconds).toBe(2537);
    }
  });

  it('parses the structured investigation answer', () => {
    const parsed = investigationAnswerSchema.parse(investigationAnswer);
    expect(parsed.status).toBe('supported');
    expect(parsed.confidence_label).toBe('high');
    expect(parsed.hypotheses).toHaveLength(2);
    expect(parsed.evidence).toHaveLength(3);
    expect(parsed.timeline).toHaveLength(2);
    expect(parsed.application_links[0]?.verified_in_database).toBe(true);
  });

  it('exposes the disproof probe on every hypothesis that ran one', () => {
    const parsed = investigationAnswerSchema.parse(investigationAnswer);
    const probed = parsed.hypotheses.filter((h) => h.disproof_searched);
    expect(probed.length).toBeGreaterThan(0);
    probed.forEach((h) => expect(h.disproof_probe).toBeTruthy());
  });

  it('surfaces contradictions with their resolution rather than hiding them', () => {
    const parsed = investigationAnswerSchema.parse(investigationAnswer);
    expect(parsed.contradictions).toHaveLength(1);
    expect(parsed.contradictions[0]?.resolution).toBeTruthy();
    expect(parsed.contradictions[0]?.detail).toBeTruthy();
  });

  it('carries the autopsy counts the forensics screen renders', () => {
    const parsed = investigationAnswerSchema.parse(investigationAnswer);
    expect(parsed.autopsy).toBeTruthy();
    expect(parsed.autopsy?.evidence_rejected).toBe(29);
    expect(Object.keys(parsed.autopsy?.rejection_reasons ?? {})).not.toHaveLength(0);
  });

  it('explains which sources were skipped and why', () => {
    const parsed = investigationAnswerSchema.parse(investigationAnswer);
    expect(parsed.explanation.reasons.length).toBeGreaterThan(0);
    expect(parsed.explanation.sources_skipped[0]?.reason).toBeTruthy();
  });

  it('parses a trace step and carries only an action summary', () => {
    const parsed = traceStepSchema.parse(traceStep);
    expect(parsed.agent).toBe('database_agent');
    expect(parsed.output_summary).toBe('1 record found');
    expect(JSON.stringify(parsed)).not.toMatch(/<think/i);
  });

  it('parses model runtime status including an unavailable GPU', () => {
    const parsed = modelRuntimeStatusSchema.parse(modelRuntimeStatus);
    expect(parsed.gpu.available).toBe(false);
    expect(parsed.gpu.detail).toMatch(/mismatch/);
    expect(parsed.models[0]?.active_model).toBe('qwen3:30b-a3b');
  });

  it('parses a degraded health report', () => {
    const parsed = healthReportSchema.parse(healthReport);
    expect(parsed.degraded).toBe(true);
    expect(parsed.components.models?.status).toBe('degraded');
  });

  it('parses a disabled agent with its alternatives', () => {
    const parsed = agentStatusSchema.array().parse(agentStatus);
    expect(parsed[0]?.enabled).toBe(false);
    expect(parsed[0]?.reason).toBeTruthy();
    expect(parsed[0]?.alternatives.length).toBeGreaterThan(0);
  });

  it('parses sources, health, assets and jobs', () => {
    expect(sourceDescriptorSchema.array().parse(sourceDescriptor)[0]?.source_id).toBe('src_docs');
    expect(sourceHealthSchema.parse(sourceHealth).status).toBe('healthy');
    expect(assetSchema.parse(asset).page_count).toBe(14);
    expect(ingestJobSchema.parse(ingestJob).stage).toBe('embedding');
  });

  it('parses a graph view', () => {
    const parsed = graphViewSchema.parse(graphView);
    expect(parsed.nodes).toHaveLength(2);
    expect(parsed.edges[0]?.type).toBe('REFERS_TO');
  });

  it('parses a canonical entity with its aliases', () => {
    const parsed = canonicalEntitySchema.parse(canonicalEntity);
    expect(parsed.canonical_name).toBe('TX82931');
    expect(parsed.aliases).toContain('Txn 82931');
  });

  it('never silently accepts a malformed payload', () => {
    expect(() => searchResponseSchema.parse({ query: 5 })).toThrow();
    expect(() => investigationAnswerSchema.parse({})).toThrow();
  });
});
