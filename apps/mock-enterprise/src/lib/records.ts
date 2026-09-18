/**
 * Type-generic record lookup shared by the API route and the detail pages.
 */
import { getAsset, getCustomer, getIncident, getTransaction } from './queries';
import type { EnterpriseRecord, RecordType } from './types';

type Loader = (id: string) => Promise<EnterpriseRecord | null>;

const LOADERS: Readonly<Record<RecordType, Loader>> = {
  customer: getCustomer,
  transaction: getTransaction,
  incident: getIncident,
  asset: getAsset,
};

/**
 * Look a record up by validated type and validated id.
 * Returns null when the id is absent from the database.
 */
export function loadRecord(type: RecordType, id: string): Promise<EnterpriseRecord | null> {
  return LOADERS[type](id);
}
