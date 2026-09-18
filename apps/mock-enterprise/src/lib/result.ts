/**
 * Explicit success/failure envelope. Pages never let a database failure escape
 * into a crash or an empty-looking table: they render an error state instead.
 */
import { DatabaseUnavailableError } from './db';

export type Result<T> = { ok: true; value: T } | { ok: false; message: string; detail?: string };

export async function attempt<T>(load: () => Promise<T>): Promise<Result<T>> {
  try {
    return { ok: true, value: await load() };
  } catch (error) {
    if (error instanceof DatabaseUnavailableError) {
      console.error('[mock-enterprise] database error:', error.detail);
      return { ok: false, message: error.message, detail: error.detail };
    }
    const message = error instanceof Error ? error.message : String(error);
    console.error('[mock-enterprise] unexpected data error:', message);
    return { ok: false, message: 'This record could not be loaded.', detail: message };
  }
}
