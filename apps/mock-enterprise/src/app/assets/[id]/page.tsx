import type { Metadata } from 'next';
import { notFound } from 'next/navigation';

import { IncidentTable } from '@/components/records/IncidentTable';
import { ErrorState } from '@/components/ui/ErrorState';
import { FieldList, type Field } from '@/components/ui/FieldList';
import { PageHeader } from '@/components/ui/PageHeader';
import { Panel } from '@/components/ui/Panel';
import { SpectraBanner } from '@/components/ui/SpectraBanner';
import { StatusChip } from '@/components/ui/StatusChip';
import { formatDateTime, formatText } from '@/lib/format';
import { getAsset, incidentsForService } from '@/lib/queries';
import { attempt } from '@/lib/result';
import type { EnterpriseAsset } from '@/lib/types';
import { isFromSpectra, parseRecordId } from '@/lib/validation';

export const dynamic = 'force-dynamic';

interface PageProps {
  params: { id: string };
  searchParams: { from?: string };
}

export function generateMetadata({ params }: PageProps): Metadata {
  const id = parseRecordId('asset', params.id);
  return { title: id ? `Asset ${id}` : 'Asset' };
}

async function loadAssetView(assetId: string) {
  const asset = await getAsset(assetId);
  if (!asset) return null;
  const incidents = asset.service ? await incidentsForService(asset.service) : [];
  return { asset, incidents };
}

function fieldsFor(asset: EnterpriseAsset): Field[] {
  return [
    { label: 'Asset ID', value: <span className="font-mono">{asset.assetId}</span> },
    { label: 'Name', value: formatText(asset.name) },
    { label: 'Kind', value: formatText(asset.kind) },
    { label: 'Owner', value: formatText(asset.owner) },
    { label: 'Environment', value: formatText(asset.environment) },
    { label: 'Service', value: formatText(asset.service) },
    { label: 'Status', value: <StatusChip value={asset.status} /> },
    { label: 'Created', value: formatDateTime(asset.createdAt) },
  ];
}

export default async function AssetDetailPage({ params, searchParams }: PageProps) {
  const assetId = parseRecordId('asset', params.id);
  if (!assetId) notFound();

  const result = await attempt(() => loadAssetView(assetId));
  if (result.ok && result.value === null) notFound();

  return (
    <>
      <SpectraBanner show={isFromSpectra(searchParams.from)} />
      <PageHeader
        title={`Asset ${assetId}`}
        subtitle={result.ok && result.value ? formatText(result.value.asset.name) : undefined}
        crumbs={[
          { label: 'Overview', href: '/' },
          { label: 'Assets', href: '/assets' },
          { label: assetId },
        ]}
      />

      {!result.ok || !result.value ? (
        <ErrorState
          message={result.ok ? 'This asset could not be loaded.' : result.message}
          detail={result.ok ? undefined : result.detail}
        />
      ) : (
        <>
          <Panel title="Asset record">
            <FieldList fields={fieldsFor(result.value.asset)} />
          </Panel>

          <Panel title="Incidents on this service" note={`${result.value.incidents.length} linked`}>
            <IncidentTable
              rows={result.value.incidents}
              caption={`Incidents affecting the service that asset ${assetId} belongs to`}
              emptyMessage="No incidents are recorded for this service."
            />
          </Panel>
        </>
      )}
    </>
  );
}
