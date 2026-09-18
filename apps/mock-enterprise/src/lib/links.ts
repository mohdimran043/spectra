/** Canonical in-app URLs. Ids always come from query results, never literals. */
import type { RecordType } from './types';

const SEGMENTS: Readonly<Record<RecordType, string>> = {
  customer: 'customers',
  transaction: 'transactions',
  incident: 'incidents',
  asset: 'assets',
};

export function listHref(type: RecordType): string {
  return `/${SEGMENTS[type]}`;
}

export function recordHref(type: RecordType, id: string): string {
  return `/${SEGMENTS[type]}/${encodeURIComponent(id)}`;
}

export const RECORD_LABELS: Readonly<Record<RecordType, string>> = {
  customer: 'Customer',
  transaction: 'Transaction',
  incident: 'Incident',
  asset: 'Asset',
};
