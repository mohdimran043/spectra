import type { z } from 'zod';

import { API_BASE_URL } from './env';
import { SpectraApiError, contractError, networkError } from './api-error';
import { apiErrorEnvelopeSchema } from './schemas/primitives';
import { readStoredRole, readStoredUserId } from './role';
import {
  agentStatusSchema,
  assetSchema,
  demoRunResponseSchema,
  demoScenarioSchema,
  healthReportSchema,
  ingestJobSchema,
  modelRuntimeStatusSchema,
  sourceDescriptorSchema,
  sourceHealthSchema,
} from './schemas/system';
import {
  databaseQueryResponseSchema,
  searchResponseSchema,
  type DatabaseQueryRequest,
  type SearchRequest,
  answerResponseSchema,
  searchHistoryEntrySchema,
} from './schemas/search';
import { z as zod } from 'zod';

const JSON_CONTENT_TYPE = 'application/json';

interface RequestOptions {
  readonly method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  readonly body?: unknown;
  readonly formData?: FormData;
  readonly signal?: AbortSignal;
  readonly searchParams?: Record<string, string | number | boolean | undefined>;
}

/** Headers the development role shim expects. Replaced wholesale by OIDC later. */
export function buildAuthHeaders(): Record<string, string> {
  return {
    'X-Spectra-Role': readStoredRole(),
    'X-Spectra-User': readStoredUserId(),
  };
}

export function buildUrl(
  path: string,
  searchParams?: RequestOptions['searchParams'],
): string {
  // In same-origin mode API_BASE_URL is empty and the request goes to /api/*
  // on whichever host served the page. `new URL(path, '')` and
  // `new URL(path, '/')` both throw, and during SSR there is no origin to
  // resolve against, so the URL is assembled as a string instead.
  const normalisedPath = path.startsWith('/') ? path : `/${path}`;
  const query = new URLSearchParams();
  if (searchParams) {
    for (const [key, value] of Object.entries(searchParams)) {
      if (value === undefined || value === '') continue;
      query.set(key, String(value));
    }
  }
  const suffix = query.toString();
  return `${API_BASE_URL}${normalisedPath}${suffix ? `?${suffix}` : ''}`;
}

async function readErrorEnvelope(
  response: Response,
  path: string,
): Promise<SpectraApiError> {
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    payload = undefined;
  }

  const parsed = apiErrorEnvelopeSchema.safeParse(payload);
  if (parsed.success) {
    return new SpectraApiError({
      kind: 'http',
      code: parsed.data.error,
      reason: parsed.data.reason,
      status: response.status,
      requestId: parsed.data.request_id ?? response.headers.get('X-Request-ID') ?? undefined,
      detail: parsed.data.detail,
      path,
    });
  }

  return new SpectraApiError({
    kind: 'http',
    code: `http_${response.status}`,
    reason: `${path} returned HTTP ${response.status} ${response.statusText || ''}`.trim() +
      ' without the documented {error, reason} envelope.',
    status: response.status,
    requestId: response.headers.get('X-Request-ID') ?? undefined,
    path,
  });
}

/**
 * The only place a fetch happens. Every response is parsed through a Zod schema
 * before any component sees it, and every failure becomes a `SpectraApiError`
 * carrying a reason the operator can read.
 */
export async function apiRequest<TSchema extends z.ZodTypeAny>(
  path: string,
  schema: TSchema,
  options: RequestOptions = {},
): Promise<z.infer<TSchema>> {
  const { method = 'GET', body, formData, signal, searchParams } = options;
  const url = buildUrl(path, searchParams);

  const headers: Record<string, string> = { ...buildAuthHeaders(), Accept: JSON_CONTENT_TYPE };
  let payload: BodyInit | undefined;

  if (formData) {
    payload = formData;
  } else if (body !== undefined) {
    headers['Content-Type'] = JSON_CONTENT_TYPE;
    payload = JSON.stringify(body);
  }

  let response: Response;
  try {
    response = await fetch(url, { method, headers, body: payload, signal, cache: 'no-store' });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause;
    throw networkError(path, cause);
  }

  if (!response.ok) throw await readErrorEnvelope(response, path);

  if (response.status === 204) return schema.parse(undefined) as z.infer<TSchema>;

  let json: unknown;
  try {
    json = await response.json();
  } catch (cause) {
    throw new SpectraApiError({
      kind: 'contract',
      code: 'invalid_json',
      status: response.status,
      path,
      reason: `${path} returned a body that is not valid JSON (${
        cause instanceof Error ? cause.message : 'unparseable'
      }).`,
    });
  }

  const parsed = schema.safeParse(json);
  if (!parsed.success) throw contractError(path, parsed.error);
  return parsed.data as z.infer<TSchema>;
}

const listOf = <T extends z.ZodTypeAny>(schema: T) => zod.array(schema);

/* ==========================================================================
 * System
 * ======================================================================= */

export const getHealth = (signal?: AbortSignal) =>
  apiRequest('/api/health', healthReportSchema, { signal });

export const getModelRuntime = (signal?: AbortSignal) =>
  apiRequest('/api/models', modelRuntimeStatusSchema, { signal });

export const unloadModelRole = (role: string) =>
  apiRequest(`/api/models/${encodeURIComponent(role)}/unload`, zod.unknown(), {
    method: 'POST',
  });

export const getAgentStatus = (signal?: AbortSignal) =>
  apiRequest('/api/agents/status', listOf(agentStatusSchema), { signal });

export const setAgentEnabled = (name: string, enabled: boolean) =>
  apiRequest(`/api/agents/${encodeURIComponent(name)}`, zod.unknown(), {
    method: 'PATCH',
    body: { enabled },
  });

/* ==========================================================================
 * Search
 * ======================================================================= */

export type SearchScope = 'unified' | 'document' | 'image' | 'video' | 'audio';

const SEARCH_PATHS: Record<SearchScope, string> = {
  unified: '/api/search',
  document: '/api/search/document',
  image: '/api/search/image',
  video: '/api/search/video',
  audio: '/api/search/audio',
};

export const runAnswer = (
  query: string,
  sourceIds: readonly string[] = [],
  signal?: AbortSignal,
) =>
  apiRequest('/api/answer', answerResponseSchema, {
    method: 'POST',
    body: { query, mode: 'fast', top_k: 8, source_ids: sourceIds },
    signal,
  });

export const listSearchHistory = (signal?: AbortSignal) =>
  apiRequest('/api/search/history', searchHistoryEntrySchema.array(), { signal });

export const clearSearchHistory = () =>
  apiRequest('/api/search/history', zod.unknown(), { method: 'DELETE' });

export const listUploadJobs = (signal?: AbortSignal) =>
  apiRequest('/api/uploads', ingestJobSchema.array(), { signal });

export const runSearch = (
  scope: SearchScope,
  request: SearchRequest,
  signal?: AbortSignal,
) => apiRequest(SEARCH_PATHS[scope], searchResponseSchema, {
  method: 'POST',
  body: request,
  signal,
});

/** Image-to-anything search with an uploaded file rather than an asset id. */
export const runImageSearch = (file: File, signal?: AbortSignal) => {
  const formData = new FormData();
  formData.append('file', file);
  return apiRequest('/api/search/image', searchResponseSchema, {
    method: 'POST',
    formData,
    signal,
  });
};

export const uploadFile = (file: File, extra?: { sourceId?: string; investigationId?: string }) => {
  const formData = new FormData();
  formData.append('file', file);
  if (extra?.sourceId) formData.append('source_id', extra.sourceId);
  if (extra?.investigationId) formData.append('investigation_id', extra.investigationId);
  return apiRequest('/api/uploads', ingestJobSchema, { method: 'POST', formData });
};

export const getUploadJob = (jobId: string, signal?: AbortSignal) =>
  apiRequest(`/api/uploads/${encodeURIComponent(jobId)}`, ingestJobSchema, { signal });

export const getAsset = (assetId: string, signal?: AbortSignal) =>
  apiRequest(`/api/assets/${encodeURIComponent(assetId)}`, assetSchema, { signal });

/** Byte-serving routes are referenced by URL, never fetched into memory. */
export const assetContentUrl = (assetId: string) =>
  buildUrl(`/api/assets/${encodeURIComponent(assetId)}/content`);

export const assetThumbnailUrl = (assetId: string) =>
  buildUrl(`/api/assets/${encodeURIComponent(assetId)}/thumbnail`);

export const assetPageUrl = (assetId: string, page: number) =>
  buildUrl(`/api/assets/${encodeURIComponent(assetId)}/page/${page}`);

/* ==========================================================================
 * Investigations
 * ======================================================================= */

export const listSources = (signal?: AbortSignal) =>
  apiRequest('/api/sources', listOf(sourceDescriptorSchema), { signal });

export const getSourceHealth = (id: string, signal?: AbortSignal) =>
  apiRequest(`/api/sources/${encodeURIComponent(id)}/health`, sourceHealthSchema, { signal });

export const syncSource = (id: string) =>
  apiRequest(`/api/sources/${encodeURIComponent(id)}/sync`, ingestJobSchema, { method: 'POST' });

export interface CreateSourceBody {
  readonly name: string;
  readonly type: string;
  readonly modalities: string[];
  readonly connection: Record<string, unknown>;
  readonly enabled: boolean;
}

export const createSource = (body: CreateSourceBody) =>
  apiRequest('/api/sources', sourceDescriptorSchema, { method: 'POST', body });

export const deleteSource = (id: string) =>
  apiRequest(`/api/sources/${encodeURIComponent(id)}`, zod.unknown(), { method: 'DELETE' });

/* ==========================================================================
 * Demo
 * ======================================================================= */

export const listDemoScenarios = (signal?: AbortSignal) =>
  apiRequest('/api/demo/scenarios', listOf(demoScenarioSchema), { signal });

export const runDemoScenario = (scenarioId: string) =>
  apiRequest(`/api/demo/run/${encodeURIComponent(scenarioId)}`, demoRunResponseSchema, {
    method: 'POST',
  });

export const seedDemoData = () =>
  apiRequest('/api/demo/seed', zod.unknown(), { method: 'POST' });

export { SpectraApiError };
