import type { Metadata } from 'next';
import { redirect } from 'next/navigation';

import { AssetTable } from '@/components/records/AssetTable';
import { CustomerTable } from '@/components/records/CustomerTable';
import { IncidentTable } from '@/components/records/IncidentTable';
import { TransactionTable } from '@/components/records/TransactionTable';
import { ErrorState } from '@/components/ui/ErrorState';
import { PageHeader } from '@/components/ui/PageHeader';
import { Panel } from '@/components/ui/Panel';
import { SearchBox } from '@/components/ui/SearchBox';
import { recordHref } from '@/lib/links';
import { loadRecord } from '@/lib/records';
import { searchEverything } from '@/lib/queries';
import { attempt } from '@/lib/result';
import { detectRecordType, parseRecordId, parseSearchTerm } from '@/lib/validation';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = { title: 'Search' };

interface PageProps {
  searchParams: { q?: string };
}

/**
 * When the term is a canonical identifier that exists, go straight to the record;
 * otherwise fall back to a contains-match across the four entity tables.
 */
async function runSearch(term: string) {
  const type = detectRecordType(term);
  const canonicalId = type ? parseRecordId(type, term) : null;
  const direct =
    type && canonicalId && (await loadRecord(type, canonicalId))
      ? recordHref(type, canonicalId)
      : null;
  return { direct, results: await searchEverything(term) };
}

export default async function SearchPage({ searchParams }: PageProps) {
  const term = parseSearchTerm(searchParams.q);

  if (!term) {
    return (
      <>
        <PageHeader title="Search" subtitle="Find a record by identifier, name or service." />
        <div className="max-w-xl">
          <SearchBox />
        </div>
      </>
    );
  }

  const result = await attempt(() => runSearch(term));
  if (result.ok && result.value.direct) {
    redirect(result.value.direct);
  }

  return (
    <>
      <PageHeader
        title="Search results"
        subtitle={`Matches for “${term}”`}
        crumbs={[{ label: 'Overview', href: '/' }, { label: 'Search' }]}
      />
      <div className="mb-4 max-w-xl">
        <SearchBox defaultValue={term} />
      </div>

      {!result.ok ? (
        <ErrorState message={result.message} detail={result.detail} />
      ) : (
        <>
          <p className="mb-4 text-ink-muted">
            {result.value.results.totalMatches} matching record
            {result.value.results.totalMatches === 1 ? '' : 's'} (10 shown per entity).
          </p>
          <Panel title="Customers">
            <CustomerTable
              rows={result.value.results.customers}
              caption={`Customers matching ${term}`}
              emptyMessage="No matching customers."
            />
          </Panel>
          <Panel title="Transactions">
            <TransactionTable
              rows={result.value.results.transactions}
              caption={`Transactions matching ${term}`}
              emptyMessage="No matching transactions."
            />
          </Panel>
          <Panel title="Incidents">
            <IncidentTable
              rows={result.value.results.incidents}
              caption={`Incidents matching ${term}`}
              emptyMessage="No matching incidents."
            />
          </Panel>
          <Panel title="Assets">
            <AssetTable
              rows={result.value.results.assets}
              caption={`Assets matching ${term}`}
              emptyMessage="No matching assets."
            />
          </Panel>
        </>
      )}
    </>
  );
}
