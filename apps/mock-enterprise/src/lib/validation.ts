/**
 * Boundary validation for every externally supplied value.
 *
 * Record types are checked against an allow-list and identifiers against a
 * strict per-type pattern BEFORE any database call is made. The patterns mirror
 * `packages/config/spectra_config/resources/applications.yaml`, which SPECTRA's
 * application resolver uses to build deep links.
 */
import type { RecordType } from './types';

export const RECORD_TYPES = ['customer', 'transaction', 'incident', 'asset'] as const;

const ID_PATTERNS: Readonly<Record<RecordType, RegExp>> = {
  customer: /^C[0-9]{4,8}$/,
  transaction: /^TX[0-9]{4,8}$/,
  incident: /^INC[0-9]{3,8}$/,
  asset: /^AST[0-9]{3,8}$/,
};

/** Longest identifier any pattern can accept; anything longer is rejected early. */
const MAX_ID_LENGTH = 16;

/** Free-text search terms are length-capped before they become a bound LIKE value. */
export const MAX_SEARCH_TERM_LENGTH = 64;

export const DEFAULT_PAGE_SIZE = 25;
const MAX_PAGE = 10_000;

export function isRecordType(value: unknown): value is RecordType {
  return typeof value === 'string' && (RECORD_TYPES as readonly string[]).includes(value);
}

/** Normalised (upper-cased) id when it matches the type's pattern, else null. */
export function parseRecordId(type: RecordType, rawId: unknown): string | null {
  if (typeof rawId !== 'string') return null;
  const candidate = rawId.trim();
  if (candidate.length === 0 || candidate.length > MAX_ID_LENGTH) return null;
  const normalised = candidate.toUpperCase();
  return ID_PATTERNS[type].test(normalised) ? normalised : null;
}

/** The record type an identifier belongs to, if any (used by search). */
export function detectRecordType(rawId: string): RecordType | null {
  for (const type of RECORD_TYPES) {
    if (parseRecordId(type, rawId) !== null) return type;
  }
  return null;
}

export function idPatternSource(type: RecordType): string {
  return ID_PATTERNS[type].source;
}

/** A 1-based page number from an untrusted query string. */
export function parsePage(raw: string | string[] | undefined): number {
  const value = Array.isArray(raw) ? raw[0] : raw;
  if (typeof value !== 'string' || !/^\d{1,5}$/.test(value)) return 1;
  const page = Number.parseInt(value, 10);
  if (!Number.isSafeInteger(page) || page < 1) return 1;
  return Math.min(page, MAX_PAGE);
}

/** A trimmed, length-capped search term, or null when there is nothing to search for. */
export function parseSearchTerm(raw: string | string[] | undefined): string | null {
  const value = Array.isArray(raw) ? raw[0] : raw;
  if (typeof value !== 'string') return null;
  const term = value.trim().slice(0, MAX_SEARCH_TERM_LENGTH);
  return term.length > 0 ? term : null;
}

/** True when the page was reached from a SPECTRA evidence deep link (`?from=spectra`). */
export function isFromSpectra(raw: string | string[] | undefined): boolean {
  const value = Array.isArray(raw) ? raw[0] : raw;
  return typeof value === 'string' && value.trim().toLowerCase() === 'spectra';
}
