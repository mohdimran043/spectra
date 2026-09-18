/**
 * Contract tests: the frontend's Zod schemas against the backend's real shapes.
 *
 * The fixtures in `__fixtures__/` are serialised from the live pydantic models
 * by `scripts/emit_frontend_fixtures.py`, so these tests fail the moment the
 * Python contract and the TypeScript contract drift apart — which is the whole
 * point of having both.
 */
import { describe, expect, it } from 'vitest';

import { buildUrl } from './api';

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
  claimSchema,
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

/** Every field `InvestigationAnswer` is allowed to put on the wire, and no other. */
const ANSWER_FIELDS = [
  'investigation_id',
  'answer',
  'confidence',
  'confidence_label',
  'status',
  'entities',
  'evidence',
  'contradictions',
  'timeline',
  'claims',
  'application_links',
  'explanation',
  'autopsy',
  'metrics',
  'degraded',
  'degraded_reasons',
  'followups',
] as const;

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
    expect(parsed.claims).toHaveLength(2);
    expect(parsed.evidence).toHaveLength(3);
    expect(parsed.timeline).toHaveLength(2);
    expect(parsed.application_links[0]?.verified_in_database).toBe(true);
  });

  it('carries each claim with the evidence for and against it', () => {
    const parsed = investigationAnswerSchema.parse(investigationAnswer);
    const claim = parsed.claims[0];
    expect(claim?.claim_id).toBeTruthy();
    expect(claim?.text).toBeTruthy();
    expect(claim?.status).toBe('supported');
    expect(claim?.supporting_evidence.length).toBeGreaterThan(0);
    expect(claim?.contradicting_evidence).toEqual([]);
    expect(claim?.verified).toBe(true);
    expect(claim?.verification_note).toBeTruthy();
  });

  /**
   * The substantive property of the new contract: a claim is judged on its own
   * evidence, so confidences are absolute readings and are free to sum past 1.
   * Anything that rendered them as shares of a whole would be lying.
   */
  it('scores claims independently rather than as shares of one total', () => {
    const parsed = investigationAnswerSchema.parse(investigationAnswer);
    const total = parsed.claims.reduce((sum, claim) => sum + claim.confidence, 0);
    expect(parsed.claims.length).toBeGreaterThan(1);
    expect(total).toBeGreaterThan(1);
    parsed.claims.forEach((claim) => {
      expect(claim.confidence).toBeGreaterThanOrEqual(0);
      expect(claim.confidence).toBeLessThanOrEqual(1);
    });
  });

  it('exposes the disproof probe on every claim that ran one', () => {
    const parsed = investigationAnswerSchema.parse(investigationAnswer);
    const probed = parsed.claims.filter((claim) => claim.disproof_searched);
    expect(probed.length).toBeGreaterThan(0);
    probed.forEach((claim) => expect(claim.disproof_probe).toBeTruthy());
  });

  it('rejects a claim status outside the closed vocabulary', () => {
    expect(() =>
      claimSchema.parse({ claim_id: 'C9', text: 'x', confidence: 0.5, status: 'disproved' }),
    ).toThrow();
    expect(claimSchema.parse({ claim_id: 'C9', text: 'x', confidence: 0.5 }).status).toBe(
      'supported',
    );
  });

  /**
   * The answer carries claims and nothing that resurrects the old field of rival
   * explanations. Asserting the whole key set — rather than the absence of one
   * name — is what keeps a retired field from creeping back under any spelling.
   */
  it('exposes exactly the fields the answer contract declares', () => {
    const parsed = investigationAnswerSchema.parse({
      ...investigationAnswer,
      rival_explanations: [{ id: 'R1', description: 'a field the contract retired' }],
    });
    expect(Object.keys(parsed).sort()).toEqual([...ANSWER_FIELDS].sort());
    expect(parsed.claims).toHaveLength(2);
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
    expect(parsed.autopsy?.claims_made).toBe(2);
    expect(parsed.autopsy?.claims_refuted).toBe(0);
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

  it('accepts a healthy component that reports no detail', () => {
    // A healthy component has nothing to explain and sends detail: null.
    // Requiring a string here rejected the whole payload and the console
    // showed "API UNREACHABLE" against a perfectly healthy API.
    expect(() =>
      healthReportSchema.parse({
        status: 'ok',
        components: { vectors: { backend: 'embedded', status: 'ok', detail: null } },
      }),
    ).not.toThrow();
  });

  it('reads backends from the top level, not from components', () => {
    // `backends` maps a store to its implementation; it has no status of its
    // own, so it must never be validated as a component.
    const parsed = healthReportSchema.parse(healthReport);
    expect(parsed.backends.relational).toBe('sqlite');
    expect(parsed.components.backends).toBeUndefined();
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

describe('URL building', () => {
  it('builds a root-relative URL in same-origin mode', () => {
    // `new URL(path, '')` throws "Invalid base URL"; the builder must not use it.
    expect(buildUrl('/api/health')).toBe('/api/health');
    expect(buildUrl('api/health')).toBe('/api/health');
  });

  it('appends query parameters and skips empty ones', () => {
    expect(buildUrl('/api/entities', { q: 'TX1', type: '', limit: 5 })).toBe(
      '/api/entities?q=TX1&limit=5',
    );
  });

  it('never throws for any documented route', () => {
    for (const path of [
      '/api/health',
      '/api/models',
      '/api/agents/status',
      '/api/search',
      '/api/investigations',
      '/api/sources',
      '/api/stream/investigation/inv_1',
    ]) {
      expect(() => buildUrl(path)).not.toThrow();
    }
  });
});
