import { type Column, DataTable } from '@/components/ui/DataTable';
import { StatusChip } from '@/components/ui/StatusChip';
import { formatDate, formatRisk, formatText } from '@/lib/format';
import type { Customer } from '@/lib/types';

import { RecordIdLink } from './RecordIdLink';

const COLUMNS: ReadonlyArray<Column<Customer>> = [
  {
    key: 'customer_id',
    header: 'Customer ID',
    cell: (row) => <RecordIdLink type="customer" id={row.customerId} />,
  },
  { key: 'name', header: 'Name', cell: (row) => formatText(row.name) },
  { key: 'segment', header: 'Segment', cell: (row) => formatText(row.segment) },
  { key: 'country', header: 'Country', cell: (row) => formatText(row.country) },
  { key: 'risk', header: 'Risk', cell: (row) => formatRisk(row.riskScore), align: 'right' },
  { key: 'status', header: 'Status', cell: (row) => <StatusChip value={row.status} /> },
  { key: 'created', header: 'Created', cell: (row) => formatDate(row.createdAt) },
];

interface CustomerTableProps {
  rows: readonly Customer[];
  caption: string;
  emptyMessage?: string;
}

export function CustomerTable({ rows, caption, emptyMessage }: CustomerTableProps) {
  return (
    <DataTable
      caption={caption}
      columns={COLUMNS}
      rows={rows}
      rowKey={(row) => row.customerId}
      emptyMessage={emptyMessage ?? 'No customers matched.'}
    />
  );
}
