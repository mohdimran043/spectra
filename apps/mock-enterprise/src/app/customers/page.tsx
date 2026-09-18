import type { Metadata } from 'next';

import { CustomerTable } from '@/components/records/CustomerTable';
import { RecordListView } from '@/components/records/RecordListView';
import { listCustomers } from '@/lib/queries';
import { attempt } from '@/lib/result';
import { parsePage } from '@/lib/validation';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = { title: 'Customers' };

interface PageProps {
  searchParams: { page?: string };
}

export default async function CustomersPage({ searchParams }: PageProps) {
  const page = parsePage(searchParams.page);
  const result = await attempt(() => listCustomers(page));

  return (
    <RecordListView
      title="Customers"
      description="Account holders, their segment and current risk rating."
      basePath="/customers"
      result={result}
      renderTable={(rows) => <CustomerTable rows={rows} caption="Customer accounts" />}
    />
  );
}
