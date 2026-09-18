/**
 * Column coercion. PostgreSQL and SQLite disagree about numerics, booleans and
 * timestamps, so every row is normalised here before it reaches a component.
 */
import type { SqlRow } from './db';
import type { Customer, EnterpriseAsset, Incident, Transaction } from './types';

export function asText(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (value instanceof Date) return value.toISOString();
  const text = String(value).trim();
  return text.length > 0 ? text : null;
}

export function asRequiredText(value: unknown, field: string): string {
  const text = asText(value);
  if (text === null) {
    throw new Error(`Expected a value for "${field}" but the column was empty.`);
  }
  return text;
}

export function asNumber(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  const parsed = typeof value === 'number' ? value : Number(String(value));
  return Number.isFinite(parsed) ? parsed : null;
}

export function asCount(value: unknown): number {
  return asNumber(value) ?? 0;
}

export function asBoolean(value: unknown): boolean | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'boolean') return value;
  if (typeof value === 'number') return value !== 0;
  const text = String(value).trim().toLowerCase();
  if (['1', 't', 'true', 'yes', 'y'].includes(text)) return true;
  if (['0', 'f', 'false', 'no', 'n'].includes(text)) return false;
  return null;
}

export function toCustomer(row: SqlRow): Customer {
  return {
    customerId: asRequiredText(row.customer_id, 'customer_id'),
    name: asText(row.name),
    email: asText(row.email),
    segment: asText(row.segment),
    country: asText(row.country),
    riskScore: asNumber(row.risk_score),
    createdAt: asText(row.created_at),
    status: asText(row.status),
  };
}

export function toTransaction(row: SqlRow): Transaction {
  return {
    transactionId: asRequiredText(row.transaction_id, 'transaction_id'),
    customerId: asText(row.customer_id),
    amount: asNumber(row.amount),
    currency: asText(row.currency),
    status: asText(row.status),
    method: asText(row.method),
    failureReason: asText(row.failure_reason),
    createdAt: asText(row.created_at),
    updatedAt: asText(row.updated_at),
    incidentId: asText(row.incident_id),
  };
}

export function toIncident(row: SqlRow): Incident {
  return {
    incidentId: asRequiredText(row.incident_id, 'incident_id'),
    title: asText(row.title),
    severity: asText(row.severity),
    status: asText(row.status),
    category: asText(row.category),
    rootCause: asText(row.root_cause),
    service: asText(row.service),
    openedAt: asText(row.opened_at),
    resolvedAt: asText(row.resolved_at),
    approved: asBoolean(row.approved),
    approvedBy: asText(row.approved_by),
  };
}

export function toAsset(row: SqlRow): EnterpriseAsset {
  return {
    assetId: asRequiredText(row.asset_id, 'asset_id'),
    name: asText(row.name),
    kind: asText(row.kind),
    owner: asText(row.owner),
    environment: asText(row.environment),
    service: asText(row.service),
    status: asText(row.status),
    createdAt: asText(row.created_at),
  };
}
