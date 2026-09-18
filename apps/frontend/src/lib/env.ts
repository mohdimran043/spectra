/**
 * Environment is read once, validated once, and never read from
 * `process.env` anywhere else. Both values are baked at build time by Next, so
 * they must be referenced as full literals for the inlining to work.
 */
const RAW_API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL;
const RAW_APP_BASE_URL = process.env.NEXT_PUBLIC_APP_BASE_URL;

// Empty means "same origin": requests go to /api/* on whichever host served
// the page, and next.config.js proxies them to the API. That works from a
// laptop, a LAN address or a port forward without a rebuild. Set
// NEXT_PUBLIC_API_BASE_URL only when the API has its own public origin.
const DEFAULT_API_BASE_URL = '';
const DEFAULT_APP_BASE_URL = 'http://localhost:3001';

function normaliseBaseUrl(value: string | undefined, fallback: string): string {
  const candidate = (value ?? '').trim() || fallback;
  if (!candidate) return '';
  return candidate.endsWith('/') ? candidate.slice(0, -1) : candidate;
}

/** Base URL of the SPECTRA API (FastAPI service). */
export const API_BASE_URL = normaliseBaseUrl(RAW_API_BASE_URL, DEFAULT_API_BASE_URL);

/** Base URL of the enterprise application SPECTRA deep-links into. */
export const APP_BASE_URL = normaliseBaseUrl(RAW_APP_BASE_URL, DEFAULT_APP_BASE_URL);

/** True when the deployment is running on the built-in defaults. */
export const IS_USING_DEFAULT_API_BASE_URL = !RAW_API_BASE_URL;
