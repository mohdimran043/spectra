import type { Metadata } from 'next';

import { AssetTable } from '@/components/records/AssetTable';
import { RecordListView } from '@/components/records/RecordListView';
import { listAssets } from '@/lib/queries';
import { attempt } from '@/lib/result';
import { parsePage } from '@/lib/validation';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = { title: 'Assets' };

interface PageProps {
  searchParams: { page?: string };
}

export default async function AssetsPage({ searchParams }: PageProps) {
  const page = parsePage(searchParams.page);
  const result = await attempt(() => listAssets(page));

  return (
    <RecordListView
      title="Assets"
      description="Infrastructure and application assets, their owner and environment."
      basePath="/assets"
      result={result}
      renderTable={(rows) => <AssetTable rows={rows} caption="Enterprise assets" />}
    />
  );
}
