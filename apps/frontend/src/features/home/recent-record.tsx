'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';

import { StatusChip, Mark } from '@/components/chip';
import { Leaf, LeafHead } from '@/components/leaf';
import { EmptyState, ErrorState, SkeletonRows } from '@/components/states';
import { listInvestigations } from '@/lib/api';
import { formatRelative, truncate } from '@/lib/format';
import { queryKeys } from '@/lib/query-keys';
import { ANSWER_STATUS_LABEL, ANSWER_STATUS_TONE, CONFIDENCE_TONE, CONFIDENCE_LABEL_TEXT } from '@/lib/vocab';

const MAX_ROWS = 8;

/**
 * The record's recent pages. Every row is a real investigation id the operator
 * can reopen; nothing here is a placeholder, so an empty list says the API has
 * no investigations rather than pretending otherwise.
 */
export function RecentRecord() {
  const query = useQuery({
    queryKey: queryKeys.investigations,
    queryFn: ({ signal }) => listInvestigations(signal),
  });

  const rows = (query.data ?? []).slice(0, MAX_ROWS);

  return (
    <Leaf className="flex min-h-0 flex-col">
      <LeafHead
        title="Recent investigations"
        count={query.data?.length}
        actions={
          <Link
            href="/demo"
            className="text-micro uppercase tracking-[0.08em] text-ink-2 underline decoration-rule-strong underline-offset-2 hover:text-ink"
          >
            Guided demo
          </Link>
        }
      />
      {query.isPending && <SkeletonRows rows={4} />}
      {query.isError && (
        <ErrorState error={query.error} context="Recent investigations" onRetry={() => query.refetch()} />
      )}
      {query.isSuccess && rows.length === 0 && (
        <EmptyState
          title="No investigations yet"
          body="Ask a question above, or run a guided demo scenario to see a full record built end to end."
        />
      )}
      {rows.length > 0 && (
        <ul className="flex flex-col">
          {rows.map((row) => {
            const question = row.question ?? row.goal ?? row.investigation_id;
            return (
              <li key={row.investigation_id}>
                <Link
                  href={`/investigations/${row.investigation_id}`}
                  className="flex flex-col gap-1 border-b border-rule px-3 py-2 last:border-b-0 hover:bg-board-sunk"
                >
                  <span className="text-body text-ink">{truncate(question, 130)}</span>
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-micro tabular text-ink-2">
                      {row.investigation_id}
                    </span>
                    {row.answer_status && (
                      <StatusChip tone={ANSWER_STATUS_TONE[row.answer_status]}>
                        {ANSWER_STATUS_LABEL[row.answer_status]}
                      </StatusChip>
                    )}
                    {row.confidence_label && (
                      <StatusChip tone={CONFIDENCE_TONE[row.confidence_label]}>
                        {CONFIDENCE_LABEL_TEXT[row.confidence_label]}
                        {row.confidence !== undefined && ` · ${row.confidence.toFixed(2)}`}
                      </StatusChip>
                    )}
                    {row.mode && <Mark>{row.mode}</Mark>}
                    <span className="ml-auto text-micro text-ink-2">
                      {formatRelative(row.updated_at ?? row.created_at)}
                    </span>
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </Leaf>
  );
}
