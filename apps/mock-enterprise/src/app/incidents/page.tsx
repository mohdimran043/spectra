import type { Metadata } from 'next';

import { IncidentTable } from '@/components/records/IncidentTable';
import { RecordListView } from '@/components/records/RecordListView';
import { listIncidents } from '@/lib/queries';
import { attempt } from '@/lib/result';
import { parsePage } from '@/lib/validation';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = { title: 'Incidents' };

interface PageProps {
  searchParams: { page?: string };
}

export default async function IncidentsPage({ searchParams }: PageProps) {
  const page = parsePage(searchParams.page);
  const result = await attempt(() => listIncidents(page));

  return (
    <RecordListView
      title="Incidents"
      description="Service incidents, severity, approval state and root cause."
      basePath="/incidents"
      result={result}
      renderTable={(rows) => <IncidentTable rows={rows} caption="Service incidents" />}
    />
  );
}
