import type { StatusTone } from '@/lib/vocab';
import { formatPercent } from '@/lib/format';
import { cn } from './cn';
import { TONE_FILL, TONE_TEXT } from './tone';

/**
 * COUNTERFORCE VISIBLE: a confidence mark never ships alone. Support and
 * contradiction share one axis, drawn from opposite ends, so the reader sees the
 * load and the counter-load in the same glyph instead of two separate stats.
 */
export function BalanceMeter({
  value,
  tone = 'held',
  supporting,
  contradicting,
  label,
  className,
}: {
  value: number;
  tone?: StatusTone;
  supporting: number;
  contradicting: number;
  label?: string;
  className?: string;
}) {
  const pct = Math.max(0, Math.min(1, value));
  const total = supporting + contradicting;
  const counterPct = total > 0 ? contradicting / total : 0;

  return (
    <div className={cn('flex flex-col gap-1', className)}>
      <div className="flex items-baseline justify-between gap-3">
        {label && <span className="text-micro uppercase tracking-[0.08em] text-ink-2">{label}</span>}
        <span className={cn('font-mono text-mark tabular font-semibold', TONE_TEXT[tone])}>
          {formatPercent(pct, 0)}
        </span>
      </div>
      <div
        className="relative h-[0.375rem] w-full border border-rule bg-board-sunk"
        role="meter"
        aria-valuenow={Math.round(pct * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label ? `${label}: ${formatPercent(pct, 0)}` : formatPercent(pct, 0)}
      >
        <div
          className={cn('absolute inset-y-0 left-0', TONE_FILL[tone])}
          style={{ width: `${pct * 100}%` }}
        />
        {counterPct > 0 && (
          <div
            className="absolute inset-y-0 right-0 bg-stamp"
            style={{ width: `${counterPct * 100}%`, opacity: 0.85 }}
          />
        )}
      </div>
      <div className="flex items-center justify-between gap-3 text-micro text-ink-2">
        <span className="tabular">
          <span className="text-seal">{supporting}</span> supporting
        </span>
        <span className="tabular">
          <span className={contradicting > 0 ? 'text-stamp font-semibold' : ''}>
            {contradicting}
          </span>{' '}
          contradicting
        </span>
      </div>
    </div>
  );
}

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
