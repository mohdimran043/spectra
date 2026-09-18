import type { ZodError } from 'zod';

import { API_BASE_URL } from './env';

export type ApiErrorKind = 'http' | 'network' | 'contract' | 'stream';

export interface ApiErrorFields {
  /** Machine code from the API envelope, or a client-side code. */
  readonly code: string;
  /** Human-readable text shown to the operator. Never a generic string. */
  readonly reason: string;
  readonly kind: ApiErrorKind;
  readonly status?: number;
  readonly requestId?: string;
  readonly detail?: Record<string, unknown>;
  readonly path?: string;
}

/**
 * The single error type the UI renders. It always carries a `reason` the
 * operator can act on, because a search that silently returns nothing is worse
 * than one that says the vector backend is unreachable.
 */
export class SpectraApiError extends Error {
  readonly code: string;
  readonly reason: string;
  readonly kind: ApiErrorKind;
  readonly status: number | undefined;
  readonly requestId: string | undefined;
  readonly detail: Record<string, unknown> | undefined;
  readonly path: string | undefined;

  constructor(fields: ApiErrorFields) {
    super(fields.reason);
    this.name = 'SpectraApiError';
    this.code = fields.code;
    this.reason = fields.reason;
    this.kind = fields.kind;
    this.status = fields.status;
    this.requestId = fields.requestId;
    this.detail = fields.detail;
    this.path = fields.path;
  }

  /** True when retrying the same call could plausibly succeed. */
  get isRetryable(): boolean {
    if (this.kind === 'network') return true;
    if (this.status === undefined) return false;
    return this.status === 429 || this.status === 503 || this.status >= 500;
  }
}

export function networkError(path: string, cause: unknown): SpectraApiError {
  const causeText = cause instanceof Error ? cause.message : String(cause);
  return new SpectraApiError({
    kind: 'network',
    code: 'api_unreachable',
    status: undefined,
    path,
    reason: `Cannot reach the SPECTRA API at ${API_BASE_URL}. The request to ${path} failed before a response arrived (${causeText}). Start the API service, or point NEXT_PUBLIC_API_BASE_URL at a running instance.`,
  });
}

export function contractError(path: string, error: ZodError): SpectraApiError {
  const issues = error.issues
    .slice(0, 4)
    .map((issue) => `${issue.path.join('.') || '<root>'}: ${issue.message}`)
    .join('; ');
  const extra = error.issues.length > 4 ? ` (+${error.issues.length - 4} more)` : '';
  return new SpectraApiError({
    kind: 'contract',
    code: 'contract_violation',
    path,
    reason: `The API response for ${path} does not match the SPECTRA contract — ${issues}${extra}. The response was rejected rather than rendered, because a mis-shaped payload here would become a mis-stated finding.`,
    detail: { issues: error.issues },
  });
}

/** Narrow an unknown thrown value into something renderable. */
export function toSpectraError(value: unknown, path = 'the API'): SpectraApiError {
  if (value instanceof SpectraApiError) return value;
  if (value instanceof Error) {
    return new SpectraApiError({
      kind: 'network',
      code: 'unexpected_error',
      path,
      reason: value.message,
    });
  }
  return new SpectraApiError({
    kind: 'network',
    code: 'unexpected_error',
    path,
    reason: `An unexpected failure occurred while talking to ${path}.`,
  });
}
