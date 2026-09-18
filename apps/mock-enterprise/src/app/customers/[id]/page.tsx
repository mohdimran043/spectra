import type { Metadata } from 'next';
import { notFound } from 'next/navigation';

import { IncidentTable } from '@/components/records/IncidentTable';
import { TransactionTable } from '@/components/records/TransactionTable';
import { ErrorState } from '@/components/ui/ErrorState';
import { FieldList, type Field } from '@/components/ui/FieldList';
import { PageHeader } from '@/components/ui/PageHeader';
import { Panel } from '@/components/ui/Panel';
import { SpectraBanner } from '@/components/ui/SpectraBanner';
import { StatusChip } from '@/components/ui/StatusChip';
import { formatDateTime, formatRisk, formatText } from '@/lib/format';
import { getCustomer, incidentsForCustomer, transactionsForCustomer } from '@/lib/queries';
import { attempt } from '@/lib/result';
import type { Customer } from '@/lib/types';
import { isFromSpectra, parseRecordId } from '@/lib/validation';

export const dynamic = 'force-dynamic';

interface PageProps {
  params: { id: string };
  searchParams: { from?: string };
}

export function generateMetadata({ params }: PageProps): Metadata {
  const id = parseRecordId('customer', params.id);
  return { title: id ? `Customer ${id}` : 'Customer' };
}

async function loadCustomerView(customerId: string) {
  const customer = await getCustomer(customerId);
  if (!customer) return null;
  const [transactions, incidents] = await Promise.all([
    transactionsForCustomer(customerId),
    incidentsForCustomer(customerId),
  ]);
  return { customer, transactions, incidents };
}

function fieldsFor(customer: Customer): Field[] {
  return [
    { label: 'Customer ID', value: <span className="font-mono">{customer.customerId}</span> },
    { label: 'Name', value: formatText(customer.name) },
    { label: 'Email', value: formatText(customer.email) },
    { label: 'Segment', value: formatText(customer.segment) },
    { label: 'Country', value: formatText(customer.country) },
    { label: 'Risk score', value: formatRisk(customer.riskScore) },
    { label: 'Account status', value: <StatusChip value={customer.status} /> },
    { label: 'Created', value: formatDateTime(customer.createdAt) },
  ];
}

export default async function CustomerDetailPage({ params, searchParams }: PageProps) {
  const customerId = parseRecordId('customer', params.id);
  if (!customerId) notFound();

  const result = await attempt(() => loadCustomerView(customerId));
  if (result.ok && result.value === null) notFound();

  return (
    <>
      <SpectraBanner show={isFromSpectra(searchParams.from)} />
      <PageHeader
        title={`Customer ${customerId}`}
        subtitle={result.ok ? formatText(result.value?.customer.name) : undefined}
        crumbs={[
          { label: 'Overview', href: '/' },
          { label: 'Customers', href: '/customers' },
          { label: customerId },
        ]}
      />

      {!result.ok || !result.value ? (
        <ErrorState
          message={result.ok ? 'This customer could not be loaded.' : result.message}
          detail={result.ok ? undefined : result.detail}
        />
      ) : (
        <>
          <Panel title="Customer record">
            <FieldList fields={fieldsFor(result.value.customer)} />
          </Panel>

          <Panel title="Transactions" note={`${result.value.transactions.length} linked`}>
            <TransactionTable
              rows={result.value.transactions}
              caption={`Transactions belonging to customer ${customerId}`}
              emptyMessage="This customer has no transactions."
            />
          </Panel>

          <Panel title="Related incidents" note="Reached through this customer's transactions">
            <IncidentTable
              rows={result.value.incidents}
              caption={`Incidents linked to customer ${customerId}`}
              emptyMessage="No incidents are linked to this customer."
            />
          </Panel>
        </>
      )}
    </>
  );
}
