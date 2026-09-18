import type { Metadata } from 'next';
import { notFound } from 'next/navigation';

import { AssetTable } from '@/components/records/AssetTable';
import { TransactionTable } from '@/components/records/TransactionTable';
import { ErrorState } from '@/components/ui/ErrorState';
import { FieldList, type Field } from '@/components/ui/FieldList';
import { PageHeader } from '@/components/ui/PageHeader';
import { Panel } from '@/components/ui/Panel';
import { SpectraBanner } from '@/components/ui/SpectraBanner';
import { StatusChip } from '@/components/ui/StatusChip';
import { formatBoolean, formatDateTime, formatText } from '@/lib/format';
import { assetsForService, getIncident, transactionsForIncident } from '@/lib/queries';
import { attempt } from '@/lib/result';
import type { Incident } from '@/lib/types';
import { isFromSpectra, parseRecordId } from '@/lib/validation';

export const dynamic = 'force-dynamic';

interface PageProps {
  params: { id: string };
  searchParams: { from?: string };
}

export function generateMetadata({ params }: PageProps): Metadata {
  const id = parseRecordId('incident', params.id);
  return { title: id ? `Incident ${id}` : 'Incident' };
}

async function loadIncidentView(incidentId: string) {
  const incident = await getIncident(incidentId);
  if (!incident) return null;
  const [transactions, assets] = await Promise.all([
    transactionsForIncident(incidentId),
    incident.service ? assetsForService(incident.service) : Promise.resolve([]),
  ]);
  return { incident, transactions, assets };
}

function fieldsFor(incident: Incident): Field[] {
  return [
    { label: 'Incident ID', value: <span className="font-mono">{incident.incidentId}</span> },
    { label: 'Severity', value: <StatusChip value={incident.severity} /> },
    { label: 'Status', value: <StatusChip value={incident.status} /> },
    { label: 'Category', value: formatText(incident.category) },
    { label: 'Affected service', value: formatText(incident.service) },
    { label: 'Opened', value: formatDateTime(incident.openedAt) },
    { label: 'Resolved', value: formatDateTime(incident.resolvedAt) },
    { label: 'Approved', value: formatBoolean(incident.approved) },
    { label: 'Approved by', value: formatText(incident.approvedBy) },
    { label: 'Title', value: formatText(incident.title), wide: true },
    { label: 'Root cause', value: formatText(incident.rootCause), wide: true },
  ];
}

export default async function IncidentDetailPage({ params, searchParams }: PageProps) {
  const incidentId = parseRecordId('incident', params.id);
  if (!incidentId) notFound();

  const result = await attempt(() => loadIncidentView(incidentId));
  if (result.ok && result.value === null) notFound();

  return (
    <>
      <SpectraBanner show={isFromSpectra(searchParams.from)} />
      <PageHeader
        title={`Incident ${incidentId}`}
        subtitle={result.ok && result.value ? formatText(result.value.incident.title) : undefined}
        crumbs={[
          { label: 'Overview', href: '/' },
          { label: 'Incidents', href: '/incidents' },
          { label: incidentId },
        ]}
      />

      {!result.ok || !result.value ? (
        <ErrorState
          message={result.ok ? 'This incident could not be loaded.' : result.message}
          detail={result.ok ? undefined : result.detail}
        />
      ) : (
        <>
          <Panel title="Incident record">
            <FieldList fields={fieldsFor(result.value.incident)} />
          </Panel>

          <Panel title="Linked transactions" note={`${result.value.transactions.length} linked`}>
            <TransactionTable
              rows={result.value.transactions}
              caption={`Transactions attached to incident ${incidentId}`}
              emptyMessage="No transactions are attached to this incident."
            />
          </Panel>

          <Panel title="Assets in the affected service">
            <AssetTable
              rows={result.value.assets}
              caption={`Assets belonging to the service affected by incident ${incidentId}`}
              emptyMessage="No assets are registered for this service."
            />
          </Panel>
        </>
      )}
    </>
  );
}
