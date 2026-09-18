'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';

import { StatusChip } from '@/components/chip';
import { Leaf, LeafHead } from '@/components/leaf';
import { ModalityGlyph } from '@/components/stamp';
import { EmptyState, ErrorState, SkeletonRows } from '@/components/states';
import { listSources } from '@/lib/api';
import { formatRelative } from '@/lib/format';
import { queryKeys } from '@/lib/query-keys';
import { SOURCE_STATUS_LABEL, SOURCE_STATUS_TONE, SOURCE_TYPE_LABEL } from '@/lib/vocab';

/** What SPECTRA is allowed to read, and whether it can currently reach it. */
export function SourceSummary() {
  const query = useQuery({
    queryKey: queryKeys.sources,
    queryFn: ({ signal }) => listSources(signal),
  });

  const sources = query.data ?? [];
  const assetTotal = sources.reduce((sum, source) => sum + source.asset_count, 0);
  const recordTotal = sources.reduce((sum, source) => sum + source.record_count, 0);

  return (
    <Leaf className="flex min-h-0 flex-col">
      <LeafHead
        title="Sources"
        count={sources.length || undefined}
        hint={
          sources.length > 0
            ? `${assetTotal.toLocaleString()} assets · ${recordTotal.toLocaleString()} records`
            : undefined
        }
        actions={
          <Link
            href="/sources"
            className="text-micro uppercase tracking-[0.08em] text-ink-2 underline decoration-rule-strong underline-offset-2 hover:text-ink"
          >
            Registry
          </Link>
        }
      />
      {query.isPending && <SkeletonRows rows={3} />}
      {query.isError && (
        <ErrorState error={query.error} context="Source registry" onRetry={() => query.refetch()} />
      )}
      {query.isSuccess && sources.length === 0 && (
        <EmptyState
          title="No sources registered"
          body="SPECTRA has nothing to read yet. Add a folder, bucket, database or API in the source registry."
        />
      )}
      {sources.length > 0 && (
        <ul className="flex flex-col">
          {sources.slice(0, 6).map((source) => (
            <li
              key={source.source_id}
              className="flex flex-wrap items-center gap-x-2.5 gap-y-1 border-b border-rule px-3 py-1.5 last:border-b-0"
            >
              <span className="flex items-center gap-1">
                {source.modalities.map((modality) => (
                  <ModalityGlyph key={modality} modality={modality} size={12} />
                ))}
              </span>
              <span className="truncate text-mark text-ink">{source.name}</span>
              <span className="text-micro text-ink-2">{SOURCE_TYPE_LABEL[source.type]}</span>
              <StatusChip tone={SOURCE_STATUS_TONE[source.status]} className="ml-auto">
                {SOURCE_STATUS_LABEL[source.status]}
              </StatusChip>
              <span className="w-full text-micro text-ink-2 sm:w-auto">
                {source.last_sync ? `synced ${formatRelative(source.last_sync)}` : 'never synced'}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Leaf>
  );
}
