'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { Button } from '@/components/button';
import { Mark, StatusChip } from '@/components/chip';
import { IconRefresh, IconVerifier } from '@/components/icons';
import { ModalityGlyph } from '@/components/stamp';
import { deleteSource, getSourceHealth, syncSource } from '@/lib/api';
import { toSpectraError } from '@/lib/api-error';
import { formatLatency, formatRelative } from '@/lib/format';
import { queryKeys } from '@/lib/query-keys';
import type { SourceDescriptor, SourceHealth } from '@/lib/schemas/system';
import { SOURCE_STATUS_LABEL, SOURCE_STATUS_TONE, SOURCE_TYPE_LABEL } from '@/lib/vocab';
import { useSession } from '@/features/shell/session-context';

/**
 * One registered source. The health check is a real request whose latency and
 * detail are printed next to it, because "healthy" without a timestamp is a
 * claim rather than a reading.
 */
export function SourceRow({ source }: { source: SourceDescriptor }) {
  const session = useSession();
  const queryClient = useQueryClient();
  const canManage = session.can('manage_sources');

  const health = useMutation<SourceHealth>({
    mutationFn: () => getSourceHealth(source.source_id),
  });

  const sync = useMutation({
    mutationFn: () => syncSource(source.source_id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.sources }),
  });

  const remove = useMutation({
    mutationFn: () => deleteSource(source.source_id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.sources }),
  });

  const checked = health.data;

  return (
    <li className="flex flex-col gap-1.5 border-b border-rule px-3 py-2.5 last:border-b-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="flex items-center gap-1">
          {source.modalities.map((modality) => (
            <ModalityGlyph key={modality} modality={modality} size={13} />
          ))}
        </span>
        <span className="text-head font-semibold text-ink">{source.name}</span>
        <Mark mono>{source.source_id}</Mark>
        <Mark>{SOURCE_TYPE_LABEL[source.type]}</Mark>
        {!source.enabled && <StatusChip tone="quiet">Disabled</StatusChip>}
        <StatusChip tone={SOURCE_STATUS_TONE[source.status]}>
          {SOURCE_STATUS_LABEL[source.status]}
        </StatusChip>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-micro text-ink-2">
        <span className="tabular">{source.asset_count.toLocaleString()} assets</span>
        <span className="tabular">{source.record_count.toLocaleString()} records</span>
        <span>
          {source.last_sync ? `last sync ${formatRelative(source.last_sync)}` : 'never synced'}
        </span>
        {source.permissions.length > 0 && (
          <span>visible to {source.permissions.join(', ')}</span>
        )}
        {source.reliability_override !== null && (
          <span className="text-caution">
            reliability overridden to {source.reliability_override}
            {source.reliability_reason ? ` — ${source.reliability_reason}` : ''}
          </span>
        )}
      </div>

      {source.status_detail && <p className="text-mark text-ink-1">{source.status_detail}</p>}

      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="secondary" onClick={() => health.mutate()} disabled={health.isPending}>
          <IconVerifier size={11} />
          {health.isPending ? 'Checking…' : 'Health check'}
        </Button>
        {canManage && (
          <>
            <Button size="sm" variant="secondary" onClick={() => sync.mutate()} disabled={sync.isPending}>
              <IconRefresh size={11} />
              {sync.isPending ? 'Queuing…' : 'Sync now'}
            </Button>
            <Button
              size="sm"
              variant="danger"
              onClick={() => remove.mutate()}
              disabled={remove.isPending}
            >
              {remove.isPending ? 'Removing…' : 'Remove'}
            </Button>
          </>
        )}

        {checked && (
          <span className="flex flex-wrap items-center gap-2 text-micro text-ink-2">
            <StatusChip tone={SOURCE_STATUS_TONE[checked.status]}>
              {SOURCE_STATUS_LABEL[checked.status]}
            </StatusChip>
            <span className="tabular">{formatLatency(checked.latency_ms)}</span>
            <span>checked {formatRelative(checked.checked_at)}</span>
            {checked.detail && <span className="text-ink-1">{checked.detail}</span>}
          </span>
        )}
      </div>

      {(health.isError || sync.isError || remove.isError) && (
        <p className="text-mark text-stamp">
          {toSpectraError(health.error ?? sync.error ?? remove.error, source.name).reason}
        </p>
      )}

      {sync.data && (
        <p className="font-mono text-micro tabular text-ink-2">
          job {sync.data.job_id} · {sync.data.status}
        </p>
      )}
    </li>
  );
}
