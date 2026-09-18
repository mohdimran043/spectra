import type { Metadata } from 'next';
import { notFound } from 'next/navigation';

import { CustomerTable } from '@/components/records/CustomerTable';
import { IncidentTable } from '@/components/records/IncidentTable';
import { RecordIdLink } from '@/components/records/RecordIdLink';
import { ErrorState } from '@/components/ui/ErrorState';
import { FieldList, type Field } from '@/components/ui/FieldList';
import { PageHeader } from '@/components/ui/PageHeader';
import { Panel } from '@/components/ui/Panel';
import { SpectraBanner } from '@/components/ui/SpectraBanner';
import { StatusChip } from '@/components/ui/StatusChip';
import { formatAmount, formatDateTime, formatText } from '@/lib/format';
import { getCustomer, getIncident, getTransaction } from '@/lib/queries';
import { attempt } from '@/lib/result';
import type { Transaction } from '@/lib/types';
import { isFromSpectra, parseRecordId } from '@/lib/validation';

export const dynamic = 'force-dynamic';

interface PageProps {
  params: { id: string };
  searchParams: { from?: string };
}

export function generateMetadata({ params }: PageProps): Metadata {
  const id = parseRecordId('transaction', params.id);
  return { title: id ? `Transaction ${id}` : 'Transaction' };
}

async function loadTransactionView(transactionId: string) {
  const transaction = await getTransaction(transactionId);
  if (!transaction) return null;
  const [customer, incident] = await Promise.all([
    transaction.customerId ? getCustomer(transaction.customerId) : Promise.resolve(null),
    transaction.incidentId ? getIncident(transaction.incidentId) : Promise.resolve(null),
  ]);
  return { transaction, customer, incident };
}

function fieldsFor(transaction: Transaction): Field[] {
  return [
    {
      label: 'Transaction ID',
      value: <span className="font-mono">{transaction.transactionId}</span>,
    },
    {
      label: 'Customer',
      value: <RecordIdLink type="customer" id={transaction.customerId} />,
    },
    { label: 'Amount', value: formatAmount(transaction.amount, transaction.currency) },
    { label: 'Currency', value: formatText(transaction.currency) },
    { label: 'Status', value: <StatusChip value={transaction.status} /> },
    { label: 'Method', value: formatText(transaction.method) },
    {
      label: 'Incident',
      value: <RecordIdLink type="incident" id={transaction.incidentId} />,
    },
    { label: 'Created', value: formatDateTime(transaction.createdAt) },
    { label: 'Last updated', value: formatDateTime(transaction.updatedAt) },
    { label: 'Failure reason', value: formatText(transaction.failureReason), wide: true },
  ];
}

export default async function TransactionDetailPage({ params, searchParams }: PageProps) {
  const transactionId = parseRecordId('transaction', params.id);
  if (!transactionId) notFound();

  const result = await attempt(() => loadTransactionView(transactionId));
  if (result.ok && result.value === null) notFound();

  return (
    <>
      <SpectraBanner show={isFromSpectra(searchParams.from)} />
      <PageHeader
        title={`Transaction ${transactionId}`}
        subtitle={
          result.ok && result.value
            ? formatAmount(result.value.transaction.amount, result.value.transaction.currency)
            : undefined
        }
        crumbs={[
          { label: 'Overview', href: '/' },
          { label: 'Transactions', href: '/transactions' },
          { label: transactionId },
        ]}
      />

      {!result.ok || !result.value ? (
        <ErrorState
          message={result.ok ? 'This transaction could not be loaded.' : result.message}
          detail={result.ok ? undefined : result.detail}
        />
      ) : (
        <>
          <Panel title="Transaction record">
            <FieldList fields={fieldsFor(result.value.transaction)} />
          </Panel>

          <Panel title="Customer">
            <CustomerTable
              rows={result.value.customer ? [result.value.customer] : []}
              caption={`Customer linked to transaction ${transactionId}`}
              emptyMessage="No customer is linked to this transaction."
            />
          </Panel>

          <Panel title="Incident">
            <IncidentTable
              rows={result.value.incident ? [result.value.incident] : []}
              caption={`Incident linked to transaction ${transactionId}`}
              emptyMessage="This transaction is not attached to an incident."
            />
          </Panel>
        </>
      )}
    </>
  );
}
