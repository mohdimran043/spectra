import type { Metadata } from 'next';

import { RecordListView } from '@/components/records/RecordListView';
import { TransactionTable } from '@/components/records/TransactionTable';
import { listTransactions } from '@/lib/queries';
import { attempt } from '@/lib/result';
import { parsePage } from '@/lib/validation';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = { title: 'Transactions' };

interface PageProps {
  searchParams: { page?: string };
}

export default async function TransactionsPage({ searchParams }: PageProps) {
  const page = parsePage(searchParams.page);
  const result = await attempt(() => listTransactions(page));

  return (
    <RecordListView
      title="Transactions"
      description="Payment attempts, their outcome and any incident they were attached to."
      basePath="/transactions"
      result={result}
      renderTable={(rows) => <TransactionTable rows={rows} caption="Payment transactions" />}
    />
  );
}
