/**
 * The single data-access seam. Every SQL statement in the application is
 * executed here, always with bound parameters, and always read-only.
 *
 * SQL is authored once using `?` placeholders and `{{table}}` table tokens;
 * this module rewrites both for the active backend.
 */
import {
  type DatabaseBackend,
  type DatabaseConfig,
  ConfigurationError,
  describeConfig,
  readDatabaseConfig,
} from './config';

export type { DatabaseBackend };

export type SqlValue = string | number | boolean | null;

export type SqlRow = Record<string, unknown>;

/** Tables the application is allowed to read. Nothing else is reachable. */
export const TABLES = ['customers', 'transactions', 'incidents', 'assets'] as const;

export type TableName = (typeof TABLES)[number];

export class DatabaseUnavailableError extends Error {
  readonly detail: string;

  constructor(detail: string, options?: { cause?: unknown }) {
    super('The enterprise database could not be reached.', options);
    this.name = 'DatabaseUnavailableError';
    this.detail = detail;
  }
}

interface Driver {
  readonly backend: DatabaseBackend;
  all(sql: string, params: readonly SqlValue[]): Promise<SqlRow[]>;
}

interface DriverCache {
  driver: Driver | null;
  config: DatabaseConfig | null;
}

const globalCache = globalThis as typeof globalThis & {
  __enterpriseDriver?: DriverCache;
};

const cache: DriverCache = (globalCache.__enterpriseDriver ??= { driver: null, config: null });

function qualify(table: TableName, config: DatabaseConfig): string {
  return config.backend === 'postgres' ? `${config.schema}.${table}` : table;
}

/** Replace `{{table}}` tokens with backend-correct, allow-listed table names. */
function resolveTables(sql: string, config: DatabaseConfig): string {
  return sql.replace(/\{\{(\w+)\}\}/g, (_match, token: string) => {
    if (!(TABLES as readonly string[]).includes(token)) {
      throw new Error(`Unknown table token "${token}" in SQL.`);
    }
    return qualify(token as TableName, config);
  });
}

/** `?` placeholders -> `$1, $2, ...` for node-postgres. */
function toNumberedPlaceholders(sql: string): string {
  let index = 0;
  return sql.replace(/\?/g, () => `$${++index}`);
}

async function createPostgresDriver(config: DatabaseConfig & { backend: 'postgres' }): Promise<Driver> {
  const { Pool } = await import('pg');
  const pool = new Pool({
    connectionString: config.connectionString,
    max: 4,
    connectionTimeoutMillis: 5_000,
    idleTimeoutMillis: 30_000,
    application_name: 'spectra-mock-enterprise',
  });
  pool.on('error', () => {
    /* Idle client failures are surfaced on the next query; never crash the server. */
  });
  return {
    backend: 'postgres',
    async all(sql, params) {
      const result = await pool.query(toNumberedPlaceholders(sql), params as unknown[]);
      return result.rows as SqlRow[];
    },
  };
}

async function createSqliteDriver(config: DatabaseConfig & { backend: 'sqlite' }): Promise<Driver> {
  const { default: Database } = await import('better-sqlite3');
  const handle = new Database(config.file, { readonly: true, fileMustExist: true });
  handle.pragma('query_only = 1');
  return {
    backend: 'sqlite',
    async all(sql, params) {
      return handle.prepare(sql).all(...(params as unknown[])) as SqlRow[];
    },
  };
}

async function getDriver(): Promise<{ driver: Driver; config: DatabaseConfig }> {
  const config = cache.config ?? readDatabaseConfig();
  cache.config = config;
  if (cache.driver) {
    return { driver: cache.driver, config };
  }
  try {
    cache.driver =
      config.backend === 'postgres'
        ? await createPostgresDriver(config)
        : await createSqliteDriver(config);
  } catch (error) {
    cache.driver = null;
    throw new DatabaseUnavailableError(
      `Could not open ${describeConfig(config)}: ${errorMessage(error)}`,
      { cause: error },
    );
  }
  return { driver: cache.driver, config };
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

/** Which backend is in use, without opening a connection. */
export function activeBackend(): DatabaseBackend {
  const config = cache.config ?? readDatabaseConfig();
  cache.config = config;
  return config.backend;
}

export function activeBackendDescription(): string {
  const config = cache.config ?? readDatabaseConfig();
  cache.config = config;
  return describeConfig(config);
}

/**
 * Run a read-only query. Throws {@link DatabaseUnavailableError} on any driver
 * or configuration failure so callers can render an explicit error state.
 */
export async function query(sql: string, params: readonly SqlValue[] = []): Promise<SqlRow[]> {
  let config: DatabaseConfig;
  let driver: Driver;
  try {
    ({ driver, config } = await getDriver());
  } catch (error) {
    if (error instanceof ConfigurationError) {
      throw new DatabaseUnavailableError(error.message, { cause: error });
    }
    throw error;
  }

  const statement = resolveTables(sql, config);
  try {
    return await driver.all(statement, params);
  } catch (error) {
    // Drop the cached driver so the next request reconnects after an outage.
    cache.driver = null;
    throw new DatabaseUnavailableError(
      `Query against ${describeConfig(config)} failed: ${errorMessage(error)}`,
      { cause: error },
    );
  }
}

/** Convenience wrapper for statements that can return at most one row. */
export async function queryOne(sql: string, params: readonly SqlValue[] = []): Promise<SqlRow | null> {
  const rows = await query(sql, params);
  return rows[0] ?? null;
}
