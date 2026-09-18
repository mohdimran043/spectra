import type { ReactNode } from 'react';

import { cn } from './cn';

/**
 * A division's page frame. One measure, one rhythm: 16px gutters on a phone,
 * 24px from `md`, and a ceiling wide enough for a three-column workspace
 * without letting a table run past a readable line.
 */
export function Division({
  children,
  className,
  width = 'wide',
}: {
  children: ReactNode;
  className?: string;
  width?: 'wide' | 'full' | 'reading';
}) {
  return (
    <div
      className={cn(
        'mx-auto w-full px-4 py-4 md:px-6 md:py-6',
        width === 'wide' && 'max-w-[104rem]',
        width === 'reading' && 'max-w-[68rem]',
        className,
      )}
    >
      {children}
    </div>
  );
}

/**
 * A division's opening statement: what this surface is for, in the product's
 * own language, plus whatever control belongs at the top of it.
 */
export function DivisionIntro({
  title,
  lede,
  actions,
  meta,
  className,
}: {
  title: string;
  lede?: string;
  actions?: ReactNode;
  meta?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('mb-4 flex flex-wrap items-end gap-x-6 gap-y-2', className)}>
      <div className="min-w-0 flex-1">
        <h2 className="text-title font-semibold text-ink">{title}</h2>
        {lede && <p className="mt-1 max-w-[62ch] text-body text-ink-2">{lede}</p>}
        {meta && <div className="mt-2 flex flex-wrap items-center gap-2">{meta}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
