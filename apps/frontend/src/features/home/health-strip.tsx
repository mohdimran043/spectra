'use client';

import Link from 'next/link';

import { cn } from '@/components/cn';
import { StatusChip } from '@/components/chip';
import { ErrorState } from '@/components/states';
import { API_BASE_URL } from '@/lib/env';
import { formatRelative } from '@/lib/format';
import { humaniseKey, type StatusTone } from '@/lib/vocab';
import { useHealth } from '@/features/shell/use-health';

const COMPONENT_TONE: Record<string, StatusTone> = {
  ok: 'seal',
  degraded: 'caution',
  error: 'stamp',
};

/**
 * One horizontal band of the machine's real state. Each cell names a component,
 * the backend actually serving it, and whether it is answering — so "embedded
 * vectors, memory cache, no generative runtime" reads as a fact rather than a
 * green tick.
 */
export function HealthStrip() {
  const health = useHealth();

  if (health.isError) {
    return (
      <ErrorState
        error={health.error}
        context="System health"
        onRetry={() => health.refetch()}
        className="px-0"
      />
    );
  }

  if (health.isPending || !health.data) {
    return (
      <div className="flex items-center gap-2 border border-rule bg-leaf px-3 py-2" aria-busy="true">
        <span className="text-micro uppercase tracking-[0.08em] text-ink-2">
          Checking {API_BASE_URL}
        </span>
        <span className="rule-progress h-px flex-1 bg-rule" />
      </div>
    );
  }

  const report = health.data;
  const entries = Object.entries(report.components);

  return (
    <div className="border border-rule bg-leaf">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-rule px-3 py-1.5">
        <span className="text-micro font-semibold uppercase tracking-[0.1em] text-ink-1">
          System health
        </span>
        <StatusChip tone={report.degraded || report.status !== 'ok' ? 'caution' : 'seal'}>
          {report.status}
        </StatusChip>
        <span className="font-mono text-micro tabular text-ink-2">v{report.version}</span>
        <span className="text-micro text-ink-2">{report.deployment_mode}</span>
        <span className="ml-auto text-micro text-ink-2">
          checked {formatRelative(report.checked_at)}
        </span>
      </div>
      <dl className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-4">
        {entries.map(([name, component], index) => (
          <div
            key={name}
            className={cn(
              'flex flex-col gap-0.5 border-rule px-3 py-2',
              'border-b',
              index % 2 === 0 && 'border-r sm:border-r',
              'sm:[&:nth-child(3n)]:border-r-0 xl:[&:nth-child(3n)]:border-r xl:[&:nth-child(4n)]:border-r-0',
            )}
          >
            <dt className="flex items-center gap-1.5 text-micro uppercase tracking-[0.08em] text-ink-2">
              {humaniseKey(name)}
            </dt>
            <dd className="flex flex-wrap items-center gap-1.5">
              <StatusChip tone={COMPONENT_TONE[component.status] ?? 'quiet'}>
                {component.status}
              </StatusChip>
              {component.backend && (
                <span className="font-mono text-micro text-ink-1">{component.backend}</span>
              )}
            </dd>
            {component.detail && (
              <p className="text-micro text-ink-2">{component.detail}</p>
            )}
          </div>
        ))}
      </dl>
      <div className="px-3 py-1.5">
        <Link
          href="/models"
          className="text-micro uppercase tracking-[0.08em] text-ink-2 underline decoration-rule-strong underline-offset-2 hover:text-ink"
        >
          Model runtime and GPU
        </Link>
      </div>
    </div>
  );
}
