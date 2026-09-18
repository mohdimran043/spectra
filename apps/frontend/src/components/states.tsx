'use client';

import type { ReactNode } from 'react';

import { SpectraApiError, toSpectraError } from '@/lib/api-error';
import { cn } from './cn';
import { Button } from './button';
import { IconRefresh, IconWarning } from './icons';

/**
 * Loading is a rule being drawn across the division it belongs to, never a
 * spinner and never a shimmering card. The skeleton reproduces the real row
 * rhythm so the layout does not jump when the record arrives.
 */
export function LoadingRule({ label }: { label: string }) {
  return (
    <div className="flex flex-col gap-1.5 px-3 py-2" role="status" aria-live="polite">
      <span className="text-micro uppercase tracking-[0.08em] text-ink-2">{label}</span>
      <div className="rule-progress h-px w-full bg-rule" />
    </div>
  );
}

export function SkeletonRows({
  rows = 4,
  className,
}: {
  rows?: number;
  className?: string;
}) {
  return (
    <div className={cn('flex flex-col', className)} aria-hidden="true">
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="flex items-center gap-3 border-b border-rule px-3 py-2.5 last:border-b-0">
          <span className="skeleton-line h-3.5 w-14 rounded-sm" />
          <span className="skeleton-line h-3 flex-1 rounded-sm" style={{ maxWidth: `${70 - index * 7}%` }} />
          <span className="skeleton-line h-3 w-10 rounded-sm" />
        </div>
      ))}
    </div>
  );
}

/**
 * An empty state names what would be here, why nothing is, and the one action
 * that would change it. It never apologises and never shows a picture.
 */
export function EmptyState({
  title,
  body,
  action,
  className,
}: {
  title: string;
  body: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('flex flex-col items-start gap-2 px-3 py-6', className)}>
      <div className="flex w-full max-w-prose flex-col gap-1.5 border-l-[1px] border-rule-strong pl-3">
        <p className="text-mark font-semibold uppercase tracking-[0.08em] text-ink-1">{title}</p>
        <p className="text-body text-ink-2">{body}</p>
      </div>
      {action && <div className="pl-3">{action}</div>}
    </div>
  );
}

/**
 * Errors are reported as the API stated them. The machine code, the request id
 * and the reason all survive to the screen, because an operator who cannot see
 * which dependency failed cannot tell a missing record from a broken index.
 */
export function ErrorState({
  error,
  onRetry,
  context,
  className,
}: {
  error: unknown;
  onRetry?: () => void;
  context?: string;
  className?: string;
}) {
  const spectraError: SpectraApiError = toSpectraError(error, context);
  return (
    <div className={cn('px-3 py-4', className)} role="alert">
      <div className="flex max-w-prose flex-col gap-2 border border-stamp bg-stamp-weak p-3">
        <div className="flex items-center gap-2 text-stamp">
          <IconWarning size={14} />
          <span className="text-micro font-semibold uppercase tracking-[0.1em]">
            {context ? `${context} failed` : 'Request failed'}
          </span>
          <span className="ml-auto font-mono text-micro tabular opacity-80">
            {spectraError.code}
            {spectraError.status ? ` · ${spectraError.status}` : ''}
          </span>
        </div>
        <p className="text-body text-ink">{spectraError.reason}</p>
        {spectraError.requestId && (
          <p className="font-mono text-micro tabular text-ink-2">
            request_id {spectraError.requestId}
          </p>
        )}
        {onRetry && spectraError.isRetryable && (
          <div>
            <Button size="sm" variant="secondary" onClick={onRetry}>
              <IconRefresh size={12} />
              Retry
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

/** A degraded band: the run produced an answer, but not on the intended path. */
export function DegradedBand({
  reasons,
  className,
}: {
  reasons: readonly string[];
  className?: string;
}) {
  if (reasons.length === 0) return null;
  return (
    <div
      className={cn('border border-caution bg-caution-weak px-3 py-2', className)}
      role="status"
    >
      <div className="flex items-center gap-2 text-caution">
        <IconWarning size={13} />
        <span className="text-micro font-semibold uppercase tracking-[0.1em]">
          Degraded path used
        </span>
      </div>
      <ul className="mt-1 flex flex-col gap-0.5">
        {reasons.map((reason) => (
          <li key={reason} className="text-mark text-ink-1">
            {reason}
          </li>
        ))}
      </ul>
    </div>
  );
}
