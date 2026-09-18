'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import type { ReactNode } from 'react';

import { Button } from '@/components/button';
import { cn } from '@/components/cn';
import { Division, DivisionIntro } from '@/components/page';
import { EmptyState, ErrorState } from '@/components/states';
import { clearSearchHistory, listSearchHistory, listUploadJobs } from '@/lib/api';
import { formatRelative } from '@/lib/format';
import type { SearchHistoryEntry } from '@/lib/schemas/search';
import type { IngestJob } from '@/lib/schemas/system';

/** Job states that mean work is still happening. */
const RUNNING: ReadonlySet<IngestJob['status']> = new Set([
  'queued',
  'processing',
  'extracting',
  'embedding',
  'indexed',
]);

/** While anything is running the list refreshes; when it settles, polling stops. */
const POLL_MS = 2000;

/**
 * What the machine is doing, and what has been asked of it.
 *
 * Two lists, in the order they matter: work still in flight at the top, because
 * it is the thing that changes, and the record of past searches underneath.
 */
export function ActivityDivision() {
  const client = useQueryClient();

  const jobs = useQuery({
    queryKey: ['upload-jobs'],
    queryFn: ({ signal }) => listUploadJobs(signal),
    refetchInterval: (query) => {
      const rows = query.state.data ?? [];
      return rows.some((job) => RUNNING.has(job.status)) ? POLL_MS : false;
    },
  });

  const history = useQuery({
    queryKey: ['search-history'],
    queryFn: ({ signal }) => listSearchHistory(signal),
  });

  const clear = useMutation({
    mutationFn: clearSearchHistory,
    onSuccess: () => client.invalidateQueries({ queryKey: ['search-history'] }),
  });

  const running = (jobs.data ?? []).filter((job) => RUNNING.has(job.status));
  const failed = (jobs.data ?? []).filter((job) => job.status === 'failed');

  return (
    <Division width="reading">
      <DivisionIntro
        title="Activity"
        lede="Work the machine is doing now, and every search that has been run against it."
      />

      <section className="mt-5" aria-labelledby="in-progress">
        <SectionHead id="in-progress" title="In progress">
          {running.length > 0 && (
            <span className="inline-flex items-center gap-1.5 text-micro text-ink-2">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-focus" aria-hidden="true" />
              refreshing
            </span>
          )}
        </SectionHead>

        {jobs.isError ? (
          <ErrorState error={jobs.error} onRetry={() => jobs.refetch()} />
        ) : running.length === 0 && failed.length === 0 ? (
          <EmptyState
            title="Nothing running"
            body="Ingestion jobs appear here while they extract, transcribe, embed and index. Upload a file or sync a source to start one."
          />
        ) : (
          <ul className="border-t border-rule">
            {[...running, ...failed].map((job) => (
              <JobRow key={job.job_id} job={job} />
            ))}
          </ul>
        )}
      </section>

      <section className="mt-8" aria-labelledby="history">
        <SectionHead id="history" title="Recent searches">
          {(history.data?.length ?? 0) > 0 && (
            <Button variant="quiet" onClick={() => clear.mutate()} disabled={clear.isPending}>
              {clear.isPending ? 'Clearing' : 'Clear history'}
            </Button>
          )}
        </SectionHead>

        {history.isError ? (
          <ErrorState error={history.error} onRetry={() => history.refetch()} />
        ) : (history.data?.length ?? 0) === 0 ? (
          <EmptyState
            title="No searches yet"
            body="Every search is recorded here with what it found, so you can see what has been asked and run it again."
          />
        ) : (
          <ul className="border-t border-rule">
            {history.data?.map((entry) => (
              <HistoryRow key={entry.search_id} entry={entry} />
            ))}
          </ul>
        )}
      </section>
    </Division>
  );
}

function SectionHead({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="mb-2 flex items-baseline justify-between gap-3">
      <h2 id={id} className="text-mark font-semibold uppercase tracking-[0.07em] text-ink-1">
        {title}
      </h2>
      {children}
    </div>
  );
}

/** One ingestion job, with the stage it is on and how far through it is. */
function JobRow({ job }: { job: IngestJob }) {
  const broken = job.status === 'failed';
  return (
    <li className="border-b border-rule px-1 py-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span
          className={cn(
            'text-micro font-semibold uppercase tracking-[0.07em]',
            broken ? 'text-stamp' : 'text-focus',
          )}
        >
          {job.status}
        </span>
        <span className="min-w-0 flex-1 truncate text-body text-ink">{job.stage}</span>
        <span className="font-mono text-micro tabular text-ink-2">
          {Math.round(job.progress * 100)}%
        </span>
        <span className="text-micro text-ink-3">{formatRelative(job.updated_at)}</span>
      </div>

      {!broken && (
        <div className="mt-1.5 h-1 w-full bg-board-sunk" role="presentation">
          <div
            className="h-full bg-focus transition-[width] duration-500"
            style={{ width: `${Math.max(2, Math.round(job.progress * 100))}%` }}
          />
        </div>
      )}

      {(job.message || job.error) && (
        <p className={cn('mt-1.5 text-micro', broken ? 'text-stamp' : 'text-ink-2')}>
          {job.error || job.message}
        </p>
      )}
      <p className="mt-1 text-micro text-ink-3">{job.source_id}</p>
    </li>
  );
}

/** One past search. Clicking it runs it again. */
function HistoryRow({ entry }: { entry: SearchHistoryEntry }) {
  const found = entry.result_count > 0;
  return (
    <li className="border-b border-rule">
      <Link
        href={`/?q=${encodeURIComponent(entry.query)}`}
        className={cn(
          'block rounded-sm px-2 py-3 transition-colors hover:bg-leaf-raised',
          'focus-visible:outline focus-visible:outline-1 focus-visible:outline-offset-2 focus-visible:outline-focus',
        )}
      >
        <span className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="min-w-0 flex-1 truncate text-body text-ink">{entry.query}</span>
          <span
            className={cn(
              'font-mono text-micro tabular',
              found ? 'text-ink-1' : 'font-semibold text-stamp',
            )}
          >
            {found ? `${entry.result_count} results` : 'nothing found'}
          </span>
          <span className="text-micro text-ink-3">{formatRelative(entry.searched_at)}</span>
        </span>

        <span className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-micro text-ink-3">
          <span className="font-mono tabular">
            {entry.candidates_screened.toLocaleString()} screened
          </span>
          <span className="font-mono tabular">{(entry.latency_ms / 1000).toFixed(2)}s</span>
          {entry.answered && <span>answered</span>}
          {entry.source_ids.length > 0 && (
            <span>
              {entry.source_ids.length} {entry.source_ids.length === 1 ? 'source' : 'sources'}
            </span>
          )}
        </span>
      </Link>
    </li>
  );
}
