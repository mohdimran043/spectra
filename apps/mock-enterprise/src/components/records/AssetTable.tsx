import { type Column, DataTable } from '@/components/ui/DataTable';
import { StatusChip } from '@/components/ui/StatusChip';
import { formatDate, formatText } from '@/lib/format';
import type { EnterpriseAsset } from '@/lib/types';

import { RecordIdLink } from './RecordIdLink';

const COLUMNS: ReadonlyArray<Column<EnterpriseAsset>> = [
  {
    key: 'asset_id',
    header: 'Asset ID',
    cell: (row) => <RecordIdLink type="asset" id={row.assetId} />,
  },
  { key: 'name', header: 'Name', cell: (row) => formatText(row.name) },
  { key: 'kind', header: 'Kind', cell: (row) => formatText(row.kind) },
  { key: 'owner', header: 'Owner', cell: (row) => formatText(row.owner) },
  { key: 'environment', header: 'Environment', cell: (row) => formatText(row.environment) },
  { key: 'service', header: 'Service', cell: (row) => formatText(row.service) },
  { key: 'status', header: 'Status', cell: (row) => <StatusChip value={row.status} /> },
  { key: 'created', header: 'Created', cell: (row) => formatDate(row.createdAt) },
];

interface AssetTableProps {
  rows: readonly EnterpriseAsset[];
  caption: string;
  emptyMessage?: string;
}

export function AssetTable({ rows, caption, emptyMessage }: AssetTableProps) {
  return (
    <DataTable
      caption={caption}
      columns={COLUMNS}
      rows={rows}
      rowKey={(row) => row.assetId}
      emptyMessage={emptyMessage ?? 'No assets matched.'}
    />
  );
}
