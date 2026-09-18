import type { ReactNode } from 'react';

import type { StatusTone } from '@/lib/vocab';
import { cn } from './cn';
import { TONE_BORDER, TONE_TEXT, TONE_WASH } from './tone';

/**
 * A status chip is a stamp: a hairline box with the status struck inside it in
 * its own ink. It never carries a dot, a pill radius or a gradient.
 */
export function StatusChip({
  tone = 'quiet',
  children,
  icon,
  title,
  className,
}: {
  tone?: StatusTone;
  children: ReactNode;
  icon?: ReactNode;
  title?: string;
  className?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        'inline-flex items-center gap-1 whitespace-nowrap rounded-sm border px-1.5 py-[0.0625rem]',
        'text-micro font-semibold uppercase tracking-[0.07em]',
        TONE_BORDER[tone],
        TONE_TEXT[tone],
        TONE_WASH[tone],
        className,
      )}
    >
      {icon}
      {children}
    </span>
  );
}

/** A quieter mark for metadata that is not a status: counts, ids, modes. */
export function Mark({
  children,
  className,
  mono = false,
}: {
  children: ReactNode;
  className?: string;
  mono?: boolean;
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 whitespace-nowrap rounded-sm border border-rule bg-board-sunk px-1.5 py-[0.0625rem] text-micro text-ink-1',
        mono && 'font-mono tabular',
        className,
      )}
    >
      {children}
    </span>
  );
}
