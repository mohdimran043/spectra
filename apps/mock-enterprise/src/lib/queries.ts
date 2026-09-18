/**
 * Every SQL statement in the application lives here. Pages and API routes call
 * these functions; they never build SQL themselves.
 *
 * Rules that hold for all statements below:
 *   * SELECT only - the application never writes.
 *   * Values are always bound parameters (`?`), never interpolated.
 *   * `{{table}}` tokens are rewritten by the data-access layer for the backend.
 */
import { query, queryOne, type SqlRow, type SqlValue } from './db';
import { asCount, toAsset, toCustomer, toIncident, toTransaction } from './rows';
import type {
  Customer,
  EnterpriseAsset,
  EntityCounts,
  Incident,
  Page,
  SearchResults,
  Transaction,
} from './types';
import { DEFAULT_PAGE_SIZE } from './validation';

const CUSTOMER_COLUMNS =
  'customer_id, name, email, segment, country, risk_score, created_at, status';
const TRANSACTION_COLUMNS =
  'transaction_id, customer_id, amount, currency, status, method, failure_reason, ' +
  'created_at, updated_at, incident_id';
const INCIDENT_COLUMNS =
  'incident_id, title, severity, status, category, root_cause, service, opened_at, ' +
  'resolved_at, approved, approved_by';
const ASSET_COLUMNS = 'asset_id, name, kind, owner, environment, service, status, created_at';

/** Hard ceiling on any related-record list rendered on a detail page. */
const RELATED_LIMIT = 100;

const SEARCH_LIMIT = 10;

async function countRows(fromClause: string, params: readonly SqlValue[] = []): Promise<number> {
  const row = await queryOne(`SELECT COUNT(*) AS total FROM ${fromClause}`, params);
  return row ? asCount(row.total) : 0;
}

interface PageSpec<T> {
  columns: string;
  table: string;
  orderBy: string;
  where?: string;
  params?: readonly SqlValue[];
  page: number;
  pageSize?: number;
  map: (row: SqlRow) => T;
}

/**
 * Shared LIMIT/OFFSET pagination. `table`, `columns`, `orderBy` and `where` are
 * module-local literals; only `params`, the page number and the page size vary,
 * and all three are bound, never interpolated.
 */
async function paginate<T>(spec: PageSpec<T>): Promise<Page<T>> {
  const pageSize = spec.pageSize ?? DEFAULT_PAGE_SIZE;
  const params = spec.params ?? [];
  const whereClause = spec.where ? ` WHERE ${spec.where}` : '';
  const total = await countRows(`${spec.table}${whereClause}`, params);
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const page = Math.min(Math.max(spec.page, 1), pageCount);
  const rows = await query(
    `SELECT ${spec.columns} FROM ${spec.table}${whereClause} ORDER BY ${spec.orderBy} LIMIT ? OFFSET ?`,
    [...params, pageSize, (page - 1) * pageSize],
  );
  return { rows: rows.map(spec.map), total, page, pageSize, pageCount };
}

/* ------------------------------------------------------------------ counts */

export async function countEntities(): Promise<EntityCounts> {
  const [customers, transactions, incidents, assets] = await Promise.all([
    countRows('{{customers}}'),
    countRows('{{transactions}}'),
    countRows('{{incidents}}'),
    countRows('{{assets}}'),
  ]);
  return { customers, transactions, incidents, assets };
}

/* --------------------------------------------------------------- customers */

export function listCustomers(page: number): Promise<Page<Customer>> {
  return paginate({
    columns: CUSTOMER_COLUMNS,
    table: '{{customers}}',
    orderBy: 'created_at DESC, customer_id ASC',
    page,
    map: toCustomer,
  });
}

export async function getCustomer(customerId: string): Promise<Customer | null> {
  const row = await queryOne(
    `SELECT ${CUSTOMER_COLUMNS} FROM {{customers}} WHERE customer_id = ?`,
    [customerId],
  );
  return row ? toCustomer(row) : null;
}

export async function transactionsForCustomer(customerId: string): Promise<Transaction[]> {
  const rows = await query(
    `SELECT ${TRANSACTION_COLUMNS} FROM {{transactions}} WHERE customer_id = ?
     ORDER BY created_at DESC, transaction_id ASC LIMIT ?`,
    [customerId, RELATED_LIMIT],
  );
  return rows.map(toTransaction);
}

/** Incidents reached through the customer's transactions. */
export async function incidentsForCustomer(customerId: string): Promise<Incident[]> {
  const rows = await query(
    `SELECT DISTINCT ${INCIDENT_COLUMNS.split(', ')
      .map((column) => `i.${column}`)
      .join(', ')}
     FROM {{incidents}} i
     JOIN {{transactions}} t ON t.incident_id = i.incident_id
     WHERE t.customer_id = ?
     ORDER BY i.opened_at DESC, i.incident_id ASC LIMIT ?`,
    [customerId, RELATED_LIMIT],
  );
  return rows.map(toIncident);
}

/* ------------------------------------------------------------ transactions */

export function listTransactions(page: number): Promise<Page<Transaction>> {
  return paginate({
    columns: TRANSACTION_COLUMNS,
    table: '{{transactions}}',
    orderBy: 'created_at DESC, transaction_id ASC',
    page,
    map: toTransaction,
  });
}

export async function getTransaction(transactionId: string): Promise<Transaction | null> {
  const row = await queryOne(
    `SELECT ${TRANSACTION_COLUMNS} FROM {{transactions}} WHERE transaction_id = ?`,
    [transactionId],
  );
  return row ? toTransaction(row) : null;
}

export async function recentTransactions(limit = 10): Promise<Transaction[]> {
  const rows = await query(
    `SELECT ${TRANSACTION_COLUMNS} FROM {{transactions}}
     ORDER BY created_at DESC, transaction_id ASC LIMIT ?`,
    [limit],
  );
  return rows.map(toTransaction);
}

/* --------------------------------------------------------------- incidents */

export function listIncidents(page: number): Promise<Page<Incident>> {
  return paginate({
    columns: INCIDENT_COLUMNS,
    table: '{{incidents}}',
    orderBy: 'opened_at DESC, incident_id ASC',
    page,
    map: toIncident,
  });
}

export async function getIncident(incidentId: string): Promise<Incident | null> {
  const row = await queryOne(
    `SELECT ${INCIDENT_COLUMNS} FROM {{incidents}} WHERE incident_id = ?`,
    [incidentId],
  );
  return row ? toIncident(row) : null;
}

/** Unresolved incidents - "open" is derived from the data, not a status vocabulary. */
export async function openIncidents(limit = 10): Promise<Incident[]> {
  const rows = await query(
    `SELECT ${INCIDENT_COLUMNS} FROM {{incidents}} WHERE resolved_at IS NULL
     ORDER BY opened_at DESC, incident_id ASC LIMIT ?`,
    [limit],
  );
  return rows.map(toIncident);
}

export async function transactionsForIncident(incidentId: string): Promise<Transaction[]> {
  const rows = await query(
    `SELECT ${TRANSACTION_COLUMNS} FROM {{transactions}} WHERE incident_id = ?
     ORDER BY created_at DESC, transaction_id ASC LIMIT ?`,
    [incidentId, RELATED_LIMIT],
  );
  return rows.map(toTransaction);
}

/* ------------------------------------------------------------------ assets */

export function listAssets(page: number): Promise<Page<EnterpriseAsset>> {
  return paginate({
    columns: ASSET_COLUMNS,
    table: '{{assets}}',
    orderBy: 'created_at DESC, asset_id ASC',
    page,
    map: toAsset,
  });
}

export async function getAsset(assetId: string): Promise<EnterpriseAsset | null> {
  const row = await queryOne(`SELECT ${ASSET_COLUMNS} FROM {{assets}} WHERE asset_id = ?`, [
    assetId,
  ]);
  return row ? toAsset(row) : null;
}

/** Assets and incidents are related through the service they belong to. */
export async function assetsForService(service: string): Promise<EnterpriseAsset[]> {
  const rows = await query(
    `SELECT ${ASSET_COLUMNS} FROM {{assets}} WHERE service = ? ORDER BY asset_id ASC LIMIT ?`,
    [service, RELATED_LIMIT],
  );
  return rows.map(toAsset);
}

export async function incidentsForService(service: string): Promise<Incident[]> {
  const rows = await query(
    `SELECT ${INCIDENT_COLUMNS} FROM {{incidents}} WHERE service = ?
     ORDER BY opened_at DESC, incident_id ASC LIMIT ?`,
    [service, RELATED_LIMIT],
  );
  return rows.map(toIncident);
}

/* ------------------------------------------------------------------ search */

/** Case-insensitive contains-match; the term is bound, wildcards included. */
export async function searchEverything(term: string): Promise<SearchResults> {
  const like = `%${term.toLowerCase()}%`;
  const [customers, transactions, incidents, assets] = await Promise.all([
    query(
      `SELECT ${CUSTOMER_COLUMNS} FROM {{customers}}
       WHERE LOWER(customer_id) LIKE ? OR LOWER(name) LIKE ? OR LOWER(email) LIKE ?
       ORDER BY customer_id ASC LIMIT ?`,
      [like, like, like, SEARCH_LIMIT],
    ),
    query(
      `SELECT ${TRANSACTION_COLUMNS} FROM {{transactions}}
       WHERE LOWER(transaction_id) LIKE ? OR LOWER(customer_id) LIKE ?
          OR LOWER(failure_reason) LIKE ?
       ORDER BY created_at DESC LIMIT ?`,
      [like, like, like, SEARCH_LIMIT],
    ),
    query(
      `SELECT ${INCIDENT_COLUMNS} FROM {{incidents}}
       WHERE LOWER(incident_id) LIKE ? OR LOWER(title) LIKE ? OR LOWER(service) LIKE ?
          OR LOWER(root_cause) LIKE ?
       ORDER BY opened_at DESC LIMIT ?`,
      [like, like, like, like, SEARCH_LIMIT],
    ),
    query(
      `SELECT ${ASSET_COLUMNS} FROM {{assets}}
       WHERE LOWER(asset_id) LIKE ? OR LOWER(name) LIKE ? OR LOWER(owner) LIKE ?
          OR LOWER(service) LIKE ?
       ORDER BY asset_id ASC LIMIT ?`,
      [like, like, like, like, SEARCH_LIMIT],
    ),
  ]);
  return {
    term,
    customers: customers.map(toCustomer),
    transactions: transactions.map(toTransaction),
    incidents: incidents.map(toIncident),
    assets: assets.map(toAsset),
    totalMatches: customers.length + transactions.length + incidents.length + assets.length,
  };
}
