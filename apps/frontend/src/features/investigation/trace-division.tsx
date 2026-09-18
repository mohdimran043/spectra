'use client';

import Link from 'next/link';

import { Mark } from '@/components/chip';
import { Division, DivisionIntro } from '@/components/page';
import { ErrorState } from '@/components/states';
import { formatLatency } from '@/lib/format';
import { AGENT_LABEL } from '@/lib/vocab';
import { BrainStatus } from './brain-status';
import { TracePanel } from './trace-panel';
import { useInvestigationRecord } from './use-investigation-record';

/**
 * The trace on its own page: the same transcript, given the whole width, with a
 * per-agent tally so a run that spent all its time in one place says so.
 */
export function TraceDivision({ investigationId }: { investigationId: string }) {
  const record = useInvestigationRecord(investigationId);
  const { stream, trace } = record;

  const byAgent = new Map<string, { count: number; latency: number }>();
  for (const step of trace) {
    const current = byAgent.get(step.agent) ?? { count: 0, latency: 0 };
    byAgent.set(step.agent, {
      count: current.count + 1,
      latency: current.latency + step.latency_ms,
    });
  }

  return (
    <Division>
      <DivisionIntro
        title="Agent trace"
        lede="Every action the Brain and its agents took, in order, with what they were asked and what they returned. Action summaries only — model reasoning is never published here."
        meta={
          <>
            <Mark mono>{investigationId}</Mark>
            <Link
              href={`/investigations/${investigationId}`}
              className="text-micro uppercase tracking-[0.08em] text-ink-2 underline decoration-rule-strong underline-offset-2 hover:text-ink"
            >
              Back to the workspace
            </Link>
          </>
        }
      />

      <div className="flex flex-col gap-3">
        <BrainStatus
          connection={stream.connection}
          status={stream.status}
          iteration={stream.iteration}
          budget={stream.budget}
          lastHeartbeatAt={stream.lastHeartbeatAt}
          attempts={stream.attempts}
        />

        {byAgent.size > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {[...byAgent.entries()]
              .sort((a, b) => b[1].latency - a[1].latency)
              .map(([agent, stats]) => (
                <span
                  key={agent}
                  className="inline-flex items-center gap-2 rounded-sm border border-rule bg-leaf px-2 py-0.5 text-mark text-ink-1"
                >
                  {AGENT_LABEL[agent as keyof typeof AGENT_LABEL] ?? agent}
                  <span className="font-mono text-micro tabular text-ink-2">{stats.count}×</span>
                  <span className="font-mono text-micro tabular text-ink">
                    {formatLatency(stats.latency)}
                  </span>
                </span>
              ))}
          </div>
        )}

        {stream.streamError && !stream.recoverable && (
          <ErrorState error={new Error(stream.streamError)} context="Investigation stream" />
        )}

        <TracePanel steps={trace} live={stream.isLive} />
      </div>
    </Division>
  );
}
