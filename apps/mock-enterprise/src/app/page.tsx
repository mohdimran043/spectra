import Link from 'next/link';

import { IncidentTable } from '@/components/records/IncidentTable';
import { TransactionTable } from '@/components/records/TransactionTable';
import { ErrorState } from '@/components/ui/ErrorState';
import { PageHeader } from '@/components/ui/PageHeader';
import { Panel } from '@/components/ui/Panel';
import { SearchBox } from '@/components/ui/SearchBox';
import { formatNumber } from '@/lib/format';
import { listHref, RECORD_LABELS } from '@/lib/links';
import { countEntities, openIncidents, recentTransactions } from '@/lib/queries';
import { attempt } from '@/lib/result';
import type { RecordType } from '@/lib/types';

export const dynamic = 'force-dynamic';

const RECENT_LIMIT = 10;

const TILE_TYPES: readonly RecordType[] = ['customer', 'transaction', 'incident', 'asset'];

async function loadOverview() {
  const [counts, transactions, incidents] = await Promise.all([
    countEntities(),
    recentTransactions(RECENT_LIMIT),
    openIncidents(RECENT_LIMIT),
  ]);
  return { counts, transactions, incidents };
}

export default async function OverviewPage() {
  const result = await attempt(loadOverview);

  return (
    <>
      <PageHeader
        title="Operations overview"
        subtitle="Customers, payment transactions, incidents and infrastructure assets."
      />
      <div className="mb-5 max-w-xl">
        <SearchBox />
      </div>

      {!result.ok ? (
        <ErrorState message={result.message} detail={result.detail} />
      ) : (
        <>
          <ul className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
            {TILE_TYPES.map((type) => {
              const key = `${type}s` as keyof typeof result.value.counts;
              return (
                <li key={type} className="border border-line bg-surface p-3">
                  <p className="field-label">{RECORD_LABELS[type]}s</p>
                  <p className="mt-1 text-2xl font-bold tabular-nums">
                    {formatNumber(result.value.counts[key])}
                  </p>
                  <Link href={listHref(type)} className="text-xxs">
                    View all {RECORD_LABELS[type].toLowerCase()}s
                  </Link>
                </li>
              );
            })}
          </ul>

          <Panel title="Recent transactions" note={`Latest ${RECENT_LIMIT}`}>
            <TransactionTable
              rows={result.value.transactions}
              caption="The most recently created transactions"
              emptyMessage="No transactions are recorded."
            />
          </Panel>

          <Panel title="Open incidents" note="Not yet resolved">
            <IncidentTable
              rows={result.value.incidents}
              caption="Incidents that have not been resolved"
              emptyMessage="No open incidents."
            />
          </Panel>
        </>
      )}
    </>
  );
}
