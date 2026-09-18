import { type Column, DataTable } from '@/components/ui/DataTable';
import { StatusChip } from '@/components/ui/StatusChip';
import { formatAmount, formatDateTime, formatText } from '@/lib/format';
import type { Transaction } from '@/lib/types';

import { RecordIdLink } from './RecordIdLink';

const COLUMNS: ReadonlyArray<Column<Transaction>> = [
  {
    key: 'transaction_id',
    header: 'Transaction ID',
    cell: (row) => <RecordIdLink type="transaction" id={row.transactionId} />,
  },
  {
    key: 'customer_id',
    header: 'Customer',
    cell: (row) => <RecordIdLink type="customer" id={row.customerId} />,
  },
  {
    key: 'amount',
    header: 'Amount',
    cell: (row) => formatAmount(row.amount, row.currency),
    align: 'right',
  },
  { key: 'status', header: 'Status', cell: (row) => <StatusChip value={row.status} /> },
  { key: 'method', header: 'Method', cell: (row) => formatText(row.method) },
  { key: 'failure', header: 'Failure reason', cell: (row) => formatText(row.failureReason) },
  {
    key: 'incident_id',
    header: 'Incident',
    cell: (row) => <RecordIdLink type="incident" id={row.incidentId} />,
  },
  { key: 'created', header: 'Created', cell: (row) => formatDateTime(row.createdAt) },
];

interface TransactionTableProps {
  rows: readonly Transaction[];
  caption: string;
  emptyMessage?: string;
}

export function TransactionTable({ rows, caption, emptyMessage }: TransactionTableProps) {
  return (
    <DataTable
      caption={caption}
      columns={COLUMNS}
      rows={rows}
      rowKey={(row) => row.transactionId}
      emptyMessage={emptyMessage ?? 'No transactions matched.'}
    />
  );
}
