import { type Column, DataTable } from '@/components/ui/DataTable';
import { StatusChip } from '@/components/ui/StatusChip';
import { formatBoolean, formatDateTime, formatText } from '@/lib/format';
import type { Incident } from '@/lib/types';

import { RecordIdLink } from './RecordIdLink';

const COLUMNS: ReadonlyArray<Column<Incident>> = [
  {
    key: 'incident_id',
    header: 'Incident ID',
    cell: (row) => <RecordIdLink type="incident" id={row.incidentId} />,
  },
  { key: 'title', header: 'Title', cell: (row) => formatText(row.title) },
  { key: 'severity', header: 'Severity', cell: (row) => <StatusChip value={row.severity} /> },
  { key: 'status', header: 'Status', cell: (row) => <StatusChip value={row.status} /> },
  { key: 'service', header: 'Service', cell: (row) => formatText(row.service) },
  { key: 'approved', header: 'Approved', cell: (row) => formatBoolean(row.approved) },
  { key: 'opened', header: 'Opened', cell: (row) => formatDateTime(row.openedAt) },
];

interface IncidentTableProps {
  rows: readonly Incident[];
  caption: string;
  emptyMessage?: string;
}

export function IncidentTable({ rows, caption, emptyMessage }: IncidentTableProps) {
  return (
    <DataTable
      caption={caption}
      columns={COLUMNS}
      rows={rows}
      rowKey={(row) => row.incidentId}
      emptyMessage={emptyMessage ?? 'No incidents matched.'}
    />
  );
}
