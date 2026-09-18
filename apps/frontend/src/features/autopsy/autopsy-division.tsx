'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';

import { Mark, StatusChip } from '@/components/chip';
import { Leaf, LeafHead, Reading } from '@/components/leaf';
import { Gauge } from '@/components/meter';
import { Division, DivisionIntro } from '@/components/page';
import { DegradedBand, EmptyState, ErrorState, SkeletonRows } from '@/components/states';
import { getInvestigationAutopsy } from '@/lib/api';
import { formatLatency, formatMegabytes, formatPercent } from '@/lib/format';
import { queryKeys } from '@/lib/query-keys';
import { humaniseKey } from '@/lib/vocab';
import { StageLatencyChart } from './latency-chart';

function CountTable({
  title,
  entries,
  emptyBody,
}: {
  title: string;
  entries: ReadonlyArray<readonly [string, number]>;
  emptyBody: string;
}) {
  const total = entries.reduce((sum, [, value]) => sum + value, 0);
  return (
    <Leaf>
      <LeafHead title={title} count={total || undefined} />
      {entries.length === 0 ? (
        <EmptyState title="Nothing recorded" body={emptyBody} />
      ) : (
        <ul className="flex flex-col">
          {entries
            .slice()
            .sort((a, b) => b[1] - a[1])
            .map(([key, value]) => (
              <li
                key={key}
                className="flex items-center gap-3 border-b border-rule px-3 py-1.5 last:border-b-0"
              >
                <span className="min-w-0 flex-1 text-mark text-ink">{humaniseKey(key)}</span>
                <span
                  className="h-1.5 bg-held"
                  style={{ width: `${total > 0 ? Math.max(3, (value / total) * 100) : 0}%`, maxWidth: '40%' }}
                  aria-hidden="true"
                />
                <span className="w-10 text-right font-mono text-mark tabular text-ink-1">{value}</span>
              </li>
            ))}
        </ul>
      )}
    </Leaf>
  );
}

/**
 * The search autopsy: what SPECTRA considered, what it kept, what it threw away
 * and why, what each tool cost, and what hardware did the work. This is the
 * product's proof of work, not a debug panel.
 */
export function AutopsyDivision({ investigationId }: { investigationId: string }) {
  const query = useQuery({
    queryKey: queryKeys.investigationAutopsy(investigationId),
    queryFn: ({ signal }) => getInvestigationAutopsy(investigationId, signal),
    retry: false,
  });

  const autopsy = query.data;
  const rejectedShare =
    autopsy && autopsy.evidence_used + autopsy.evidence_rejected > 0
      ? autopsy.evidence_rejected / (autopsy.evidence_used + autopsy.evidence_rejected)
      : 0;

  return (
    <Division>
      <DivisionIntro
        title="Search autopsy"
        lede="Everything the investigation touched, including what it rejected. An answer whose rejections cannot be inspected is an answer nobody can audit."
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

      {query.isPending && (
        <Leaf>
          <LeafHead title="Loading autopsy" />
          <SkeletonRows rows={5} />
        </Leaf>
      )}

      {query.isError && (
        <ErrorState error={query.error} context="Search autopsy" onRetry={() => query.refetch()} />
      )}

      {autopsy && (
        <div className="flex flex-col gap-3">
          {autopsy.degraded && <DegradedBand reasons={autopsy.degraded_reasons} />}

          <Leaf>
            <LeafHead title="Headline readings" />
            <div className="grid grid-cols-2 gap-x-6 gap-y-3 p-3 md:grid-cols-4 xl:grid-cols-6">
              <Reading label="Total latency" value={formatLatency(autopsy.total_latency_ms)} />
              <Reading label="Tool calls" value={String(autopsy.tool_calls)} />
              <Reading label="Candidates retrieved" value={autopsy.candidates_retrieved.toLocaleString()} />
              <Reading label="Evidence used" value={String(autopsy.evidence_used)} />
              <Reading
                label="Evidence rejected"
                value={String(autopsy.evidence_rejected)}
                tone={autopsy.evidence_rejected > 0 ? 'text-caution' : undefined}
              />
              <Reading
                label="Contradictions"
                value={String(autopsy.contradictions)}
                tone={autopsy.contradictions > 0 ? 'text-stamp font-semibold' : undefined}
              />
              <Reading label="Claims made" value={String(autopsy.claims_made)} />
              <Reading
                label="Claims refuted"
                value={String(autopsy.claims_refuted)}
                tone={autopsy.claims_refuted > 0 ? 'text-caution' : undefined}
              />
              <Reading label="GPU peak" value={formatMegabytes(autopsy.gpu_peak_mb)} />
              <Reading label="Sources considered" value={String(autopsy.sources_considered.length)} />
            </div>

            <div className="grid gap-4 border-t border-rule p-3 md:grid-cols-2">
              <Gauge
                value={autopsy.evidence_diversity}
                tone={autopsy.evidence_diversity >= 0.6 ? 'seal' : autopsy.evidence_diversity >= 0.3 ? 'caution' : 'stamp'}
                label="Evidence diversity"
                reading={formatPercent(autopsy.evidence_diversity, 0)}
              />
              <Gauge
                value={rejectedShare}
                tone="caution"
                label="Share of considered evidence rejected"
                reading={formatPercent(rejectedShare, 0)}
              />
            </div>
            <p className="border-t border-rule px-3 py-1.5 text-micro text-ink-2">
              Diversity counts distinct sources, distinct modalities and distinct assets, so three
              paragraphs of one PDF cannot outrank a database record plus a document plus a video.
            </p>
          </Leaf>

          <div className="grid gap-3 xl:grid-cols-2">
            <Leaf>
              <LeafHead title="Per-stage latency" count={Object.keys(autopsy.stage_latency_ms).length} />
              {Object.keys(autopsy.stage_latency_ms).length === 0 ? (
                <EmptyState
                  title="No stage timings"
                  body="The run did not record per-stage latency. Only the total is available."
                />
              ) : (
                <div className="p-2">
                  <StageLatencyChart stages={autopsy.stage_latency_ms} />
                </div>
              )}
            </Leaf>

            <CountTable
              title="Tool calls by tool"
              entries={Object.entries(autopsy.tool_breakdown)}
              emptyBody="No tool breakdown was recorded for this run."
            />
          </div>

          <div className="grid gap-3 xl:grid-cols-2">
            <CountTable
              title="Why evidence was rejected"
              entries={Object.entries(autopsy.rejection_reasons)}
              emptyBody="Nothing retrieved was rejected, or the reasons were not recorded."
            />

            <Leaf>
              <LeafHead title="Sources and models" />
              <div className="flex flex-col gap-3 p-3">
                <div>
                  <p className="text-micro uppercase tracking-[0.08em] text-ink-2">
                    Sources considered
                  </p>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {autopsy.sources_considered.length === 0 ? (
                      <span className="text-mark text-ink-2">None recorded.</span>
                    ) : (
                      autopsy.sources_considered.map((source) => <Mark key={source} mono>{source}</Mark>)
                    )}
                  </div>
                </div>
                <div>
                  <p className="text-micro uppercase tracking-[0.08em] text-ink-2">Models used</p>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {autopsy.models_used.length === 0 ? (
                      <StatusChip tone="caution">
                        No model recorded — the run used a non-generative path
                      </StatusChip>
                    ) : (
                      autopsy.models_used.map((model) => <Mark key={model} mono>{model}</Mark>)
                    )}
                  </div>
                </div>
              </div>
            </Leaf>
          </div>
        </div>
      )}
    </Division>
  );
}
