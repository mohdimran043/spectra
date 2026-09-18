'use client';

import { StatusChip } from '@/components/chip';
import { cn } from '@/components/cn';
import { Leaf, LeafHead } from '@/components/leaf';
import { EmptyState } from '@/components/states';
import { formatLatency } from '@/lib/format';
import type { TraceStep } from '@/lib/schemas/investigation';
import { AGENT_LABEL, TRACE_STATUS_LABEL, TRACE_STATUS_TONE } from '@/lib/vocab';
import { AgentGlyph } from './agent-glyph';

/**
 * The transcript. Each step is a numbered line that is written once and never
 * rewritten, carrying what the agent was asked, what it returned, and how long
 * it took.
 *
 * Action summaries only. `input_summary` and `output_summary` are what the API
 * publishes and what this renders; model chain-of-thought is not exposed here
 * and there is no field on `TraceStep` that would carry it.
 */
export function TracePanel({
  steps,
  live,
  className,
  dense = false,
}: {
  steps: readonly TraceStep[];
  live: boolean;
  className?: string;
  dense?: boolean;
}) {
  const latest = steps[steps.length - 1];

  return (
    <Leaf className={cn('flex min-h-0 flex-col', className)}>
      <LeafHead
        title="Agent trace"
        count={steps.length}
        hint="Action summaries only"
        actions={
          live ? (
            <StatusChip tone="held">Streaming</StatusChip>
          ) : (
            <StatusChip tone="quiet">Complete</StatusChip>
          )
        }
      />

      {/* The live region announces only the newest line, not the whole list. */}
      <p aria-live="polite" aria-atomic="true" className="sr-only">
        {latest
          ? `Step ${latest.sequence}. ${AGENT_LABEL[latest.agent]}. ${
              TRACE_STATUS_LABEL[latest.status]
            }. ${latest.output_summary || latest.title}`
          : 'No trace steps yet.'}
      </p>

      {steps.length === 0 ? (
        <EmptyState
          title="No steps yet"
          body="The Brain publishes a step for every action it takes. They appear here as they happen."
        />
      ) : (
        <ol className="min-h-0 flex-1 overflow-y-auto">
          {steps.map((step) => (
            <li
              key={step.step_id}
              className={cn(
                'grid grid-cols-[2.25rem_1.25rem_minmax(0,1fr)] items-start gap-x-2 border-b border-rule px-3 last:border-b-0',
                dense ? 'py-1.5' : 'py-2',
              )}
            >
              <span className="pt-[0.1875rem] text-right font-mono text-micro tabular text-ink-2">
                {String(step.sequence).padStart(3, '0')}
              </span>
              <span
                className={cn(
                  'pt-[0.125rem]',
                  step.status === 'error' ? 'text-stamp' : 'text-ink-1',
                )}
              >
                <AgentGlyph agent={step.agent} size={13} />
              </span>
              <div className="min-w-0">
                <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                  <span className="text-mark font-semibold text-ink">
                    {step.title || AGENT_LABEL[step.agent]}
                  </span>
                  <StatusChip tone={TRACE_STATUS_TONE[step.status]}>
                    {TRACE_STATUS_LABEL[step.status]}
                  </StatusChip>
                  {step.tool && (
                    <span className="font-mono text-micro text-ink-2">{step.tool}</span>
                  )}
                  <span className="ml-auto font-mono text-micro tabular text-ink-2">
                    {formatLatency(step.latency_ms)}
                  </span>
                </div>
                {step.input_summary && (
                  <p className="mt-0.5 text-mark text-ink-2">
                    <span className="text-ink-3">asked </span>
                    {step.input_summary}
                  </p>
                )}
                {step.output_summary && (
                  <p className="mt-0.5 text-mark text-ink">{step.output_summary}</p>
                )}
                {step.error && <p className="mt-0.5 text-mark text-stamp">{step.error}</p>}
                {step.evidence_ids.length > 0 && (
                  <p className="mt-0.5 font-mono text-micro tabular text-ink-2">
                    {step.evidence_ids.length} evidence{' '}
                    {step.evidence_ids.length === 1 ? 'item' : 'items'} recorded
                  </p>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
    </Leaf>
  );
}
