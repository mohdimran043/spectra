/**
 * Data-access configuration, resolved once from the environment.
 *
 * The application NEVER carries its own copy of the enterprise data: it reads
 * whichever database the demo dataset was loaded into.
 */
import path from 'node:path';

export type DatabaseBackend = 'postgres' | 'sqlite';

/** Default location of the SQLite demo database, relative to this app. */
const DEFAULT_SQLITE_PATH = '../../data/runtime/enterprise.db';

/** PostgreSQL schema holding the enterprise demo tables. */
const DEFAULT_PG_SCHEMA = 'enterprise';

/** A schema identifier can never be parameterised, so it is strictly validated. */
const SCHEMA_PATTERN = /^[a-z_][a-z0-9_]{0,62}$/;

export interface PostgresConfig {
  readonly backend: 'postgres';
  readonly connectionString: string;
  readonly schema: string;
}

export interface SqliteConfig {
  readonly backend: 'sqlite';
  readonly file: string;
}

export type DatabaseConfig = PostgresConfig | SqliteConfig;

export class ConfigurationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ConfigurationError';
  }
}

function resolveSchema(raw: string | undefined): string {
  const schema = (raw ?? DEFAULT_PG_SCHEMA).trim();
  if (!SCHEMA_PATTERN.test(schema)) {
    throw new ConfigurationError(
      `ENTERPRISE_PG_SCHEMA must be a plain lowercase identifier, received "${schema}".`,
    );
  }
  return schema;
}

function resolveSqliteFile(raw: string | undefined): string {
  const candidate = (raw ?? DEFAULT_SQLITE_PATH).trim();
  if (candidate.length === 0) {
    throw new ConfigurationError('ENTERPRISE_SQLITE_PATH is set but empty.');
  }
  return path.resolve(process.cwd(), candidate);
}

/**
 * PostgreSQL when DATABASE_URL is present, SQLite otherwise (development default).
 */
export function readDatabaseConfig(env: NodeJS.ProcessEnv = process.env): DatabaseConfig {
  const databaseUrl = env.DATABASE_URL?.trim();
  if (databaseUrl) {
    return {
      backend: 'postgres',
      connectionString: databaseUrl,
      schema: resolveSchema(env.ENTERPRISE_PG_SCHEMA),
    };
  }
  return { backend: 'sqlite', file: resolveSqliteFile(env.ENTERPRISE_SQLITE_PATH) };
}

/** Human-readable description of where the data is being read from. */
export function describeConfig(config: DatabaseConfig): string {
  return config.backend === 'postgres'
    ? `PostgreSQL (schema "${config.schema}")`
    : `SQLite (${config.file})`;
}
