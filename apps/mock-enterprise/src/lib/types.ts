/** Row shapes of the enterprise demo schema, normalised for rendering. */

export interface Customer {
  customerId: string;
  name: string | null;
  email: string | null;
  segment: string | null;
  country: string | null;
  riskScore: number | null;
  createdAt: string | null;
  status: string | null;
}

export interface Transaction {
  transactionId: string;
  customerId: string | null;
  amount: number | null;
  currency: string | null;
  status: string | null;
  method: string | null;
  failureReason: string | null;
  createdAt: string | null;
  updatedAt: string | null;
  incidentId: string | null;
}

export interface Incident {
  incidentId: string;
  title: string | null;
  severity: string | null;
  status: string | null;
  category: string | null;
  rootCause: string | null;
  service: string | null;
  openedAt: string | null;
  resolvedAt: string | null;
  approved: boolean | null;
  approvedBy: string | null;
}

export interface EnterpriseAsset {
  assetId: string;
  name: string | null;
  kind: string | null;
  owner: string | null;
  environment: string | null;
  service: string | null;
  status: string | null;
  createdAt: string | null;
}

export type RecordType = 'customer' | 'transaction' | 'incident' | 'asset';

export type EnterpriseRecord = Customer | Transaction | Incident | EnterpriseAsset;

export interface EntityCounts {
  customers: number;
  transactions: number;
  incidents: number;
  assets: number;
}

export interface Page<T> {
  rows: T[];
  total: number;
  page: number;
  pageSize: number;
  pageCount: number;
}

export interface SearchResults {
  term: string;
  customers: Customer[];
  transactions: Transaction[];
  incidents: Incident[];
  assets: EnterpriseAsset[];
  totalMatches: number;
}
