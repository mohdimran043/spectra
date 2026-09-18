'use client';

import { Mark } from '@/components/chip';
import { cn } from '@/components/cn';
import { Leaf, LeafHead } from '@/components/leaf';
import { EmptyState } from '@/components/states';
import { ModalityGlyph } from '@/components/stamp';
import { formatClock, formatDate } from '@/lib/format';
import type { TimelineEvent } from '@/lib/schemas/evidence';

/**
 * The chronology. Selecting an event filters the evidence ledger to the exhibits
 * that event was built from — CONSTRAINT PROPAGATION: one selection re-marks the
 * whole record rather than opening a second, disconnected list.
 */
export function TimelinePanel({
  events,
  selectedEventId,
  onSelect,
  className,
}: {
  events: readonly TimelineEvent[];
  selectedEventId: string | null;
  onSelect: (event: TimelineEvent | null) => void;
  className?: string;
}) {
  const ordered = [...events].sort(
    (a, b) => new Date(a.occurred_at).getTime() - new Date(b.occurred_at).getTime(),
  );

  let previousDate = '';

  return (
    <Leaf className={cn('flex min-h-0 flex-col', className)}>
      <LeafHead
        title="Timeline"
        count={events.length}
        hint="Select an event to filter the ledger"
        actions={
          selectedEventId && (
            <button
              type="button"
              onClick={() => onSelect(null)}
              className="text-micro uppercase tracking-[0.08em] text-ink-2 underline decoration-rule-strong underline-offset-2 hover:text-ink"
            >
              Clear
            </button>
          )
        }
      />
      {ordered.length === 0 ? (
        <EmptyState
          title="No dated events"
          body="A timeline is built from evidence that carries an occurrence time. Nothing retrieved for this question did."
        />
      ) : (
        <ol className="min-h-0 flex-1 overflow-y-auto">
          {ordered.map((event) => {
            const day = formatDate(event.occurred_at);
            const showDay = day !== previousDate;
            previousDate = day;
            const selected = event.event_id === selectedEventId;

            return (
              <li key={event.event_id}>
                {showDay && (
                  <p className="sticky top-0 z-10 border-b border-rule bg-board-sunk px-3 py-0.5 text-micro uppercase tracking-[0.1em] text-ink-2">
                    {day}
                  </p>
                )}
                <button
                  type="button"
                  aria-pressed={selected}
                  onClick={() => onSelect(selected ? null : event)}
                  className={cn(
                    'flex w-full items-start gap-2.5 border-b border-rule px-3 py-1.5 text-left',
                    selected ? 'bg-held-weak' : 'hover:bg-board-sunk',
                  )}
                >
                  <time
                    dateTime={event.occurred_at}
                    className="shrink-0 pt-[0.0625rem] font-mono text-mark tabular text-ink-1"
                  >
                    {formatClock(event.occurred_at)}
                  </time>
                  <ModalityGlyph modality={event.modality} size={12} className="mt-[0.1875rem]" />
                  <span className="min-w-0 flex-1">
                    <span className="block text-body text-ink">{event.label}</span>
                    {event.detail && (
                      <span className="block text-micro text-ink-2">{event.detail}</span>
                    )}
                  </span>
                  <span className="flex shrink-0 items-center gap-1.5">
                    {event.precision !== 'exact' && <Mark>{event.precision}</Mark>}
                    {event.evidence_ids.length > 0 && (
                      <span className="font-mono text-micro tabular text-ink-2">
                        {event.evidence_ids.length}
                      </span>
                    )}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      )}
    </Leaf>
  );
}
