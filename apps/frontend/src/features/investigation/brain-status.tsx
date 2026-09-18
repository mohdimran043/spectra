'use client';

import { Mark, StatusChip } from '@/components/chip';
import { Gauge } from '@/components/meter';
import { formatRelative } from '@/lib/format';
import type { BudgetState } from '@/lib/schemas/investigation';
import type { ConnectionState } from './use-investigation-stream';

const CONNECTION_COPY: Record<ConnectionState, { tone: 'seal' | 'held' | 'caution' | 'stamp' | 'quiet'; label: string; detail: string }> = {
  idle: { tone: 'quiet', label: 'Idle', detail: 'No stream requested.' },
  connecting: { tone: 'held', label: 'Connecting', detail: 'Opening the event stream.' },
  open: { tone: 'held', label: 'Live', detail: 'Receiving events from the Brain.' },
  closed: { tone: 'quiet', label: 'Closed', detail: 'The stream ended.' },
  failed: { tone: 'stamp', label: 'Dropped', detail: 'The stream could not be resumed.' },
};

/**
 * What the Brain is doing right now, and what it has left to spend. Budget is
 * shown because an answer produced against an exhausted budget is a different
 * kind of answer, and the operator is entitled to know which one they have.
 */
export function BrainStatus({
  connection,
  status,
  iteration,
  budget,
  lastHeartbeatAt,
  attempts,
}: {
  connection: ConnectionState;
  status: string | null;
  iteration: number | null;
  budget: BudgetState | null;
  lastHeartbeatAt: number | null;
  attempts: number;
}) {
  const copy = CONNECTION_COPY[connection];
  const toolCallsUsed = budget?.tool_calls_used ?? 0;
  const maxToolCalls = budget?.max_tool_calls ?? 0;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border border-rule bg-leaf px-3 py-2">
      <div className="flex items-center gap-2">
        <span className="text-micro font-semibold uppercase tracking-[0.1em] text-ink-1">Brain</span>
        <StatusChip tone={copy.tone}>{copy.label}</StatusChip>
        {status && <Mark>{status}</Mark>}
        {iteration !== null && <Mark mono>iteration {iteration}</Mark>}
      </div>

      {budget && maxToolCalls > 0 && (
        <div className="min-w-[10rem] flex-1 md:max-w-[18rem]">
          <Gauge
            value={toolCallsUsed}
            max={maxToolCalls}
            tone={toolCallsUsed / maxToolCalls > 0.85 ? 'caution' : 'held'}
            label="Tool budget"
            reading={`${toolCallsUsed} / ${maxToolCalls}`}
          />
        </div>
      )}

      {budget?.exhausted_reason && (
        <StatusChip tone="caution">Budget exhausted · {budget.exhausted_reason}</StatusChip>
      )}

      <p className="ml-auto text-micro text-ink-2">
        {copy.detail}
        {connection === 'open' && lastHeartbeatAt
          ? ` Last heartbeat ${formatRelative(new Date(lastHeartbeatAt).toISOString())}.`
          : ''}
        {connection === 'connecting' && attempts > 1 ? ` Attempt ${attempts}.` : ''}
      </p>
    </div>
  );
}
