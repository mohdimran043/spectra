import type { StatusTone } from '@/lib/vocab';
import { cn } from './cn';
import { TONE_FILL } from './tone';

/** A plain proportional reading: VRAM, utilisation, diversity, relevance. */
export function Gauge({
  value,
  max = 1,
  tone = 'held',
  label,
  reading,
  className,
  compact = false,
}: {
  value: number;
  max?: number;
  tone?: StatusTone;
  label?: string;
  reading?: string;
  className?: string;
  compact?: boolean;
}) {
  const ratio = max > 0 ? Math.max(0, Math.min(1, value / max)) : 0;
  return (
    <div className={cn('flex flex-col gap-1', className)}>
      {(label || reading) && (
        <div className="flex items-baseline justify-between gap-3">
          {label && (
            <span className="text-micro uppercase tracking-[0.08em] text-ink-2">{label}</span>
          )}
          {reading && (
            <span className="font-mono text-mark tabular text-ink">{reading}</span>
          )}
        </div>
      )}
      <div
        className={cn('relative w-full border border-rule bg-board-sunk', compact ? 'h-1' : 'h-[0.375rem]')}
        role="meter"
        aria-valuenow={Math.round(ratio * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label ?? 'value'}
      >
        <div
          className={cn('absolute inset-y-0 left-0', TONE_FILL[tone])}
          style={{ width: `${ratio * 100}%` }}
        />
      </div>
    </div>
  );
}

/**
 * A 6-cell struck scale — the record's compact way of printing a 0–1 score in a
 * table row without spending a whole bar on it.
 */
export function ScaleMark({
  value,
  tone = 'held',
  title,
}: {
  value: number;
  tone?: StatusTone;
  title?: string;
}) {
  const filled = Math.round(Math.max(0, Math.min(1, value)) * 6);
  return (
    <span className="inline-flex items-center gap-[2px]" title={title} aria-hidden="true">
      {Array.from({ length: 6 }, (_, index) => (
        <span
          key={index}
          className={cn(
            'block h-2.5 w-[3px]',
            index < filled ? TONE_FILL[tone] : 'bg-rule',
          )}
        />
      ))}
    </span>
  );
}
