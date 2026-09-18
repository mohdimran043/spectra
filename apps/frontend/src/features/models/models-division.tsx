'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { Button } from '@/components/button';
import { Mark, StatusChip } from '@/components/chip';
import { cn } from '@/components/cn';
import { Disclosure } from '@/components/disclosure';
import { Leaf, LeafHead } from '@/components/leaf';
import { Division, DivisionIntro } from '@/components/page';
import { EmptyState, ErrorState, SkeletonRows } from '@/components/states';
import { getModelRuntime, unloadModelRole } from '@/lib/api';
import { formatLatency, formatMegabytes, formatRelative } from '@/lib/format';
import { POLL_INTERVAL_MS, queryKeys } from '@/lib/query-keys';
import type { ModelInfo } from '@/lib/schemas/system';
import { MODEL_ROLE_PURPOSE, MODEL_STATE_LABEL, MODEL_STATE_TONE } from '@/lib/vocab';
import { useSession } from '@/features/shell/session-context';
import { GpuCard } from './gpu-card';

function averageLatency(model: ModelInfo): number {
  return model.call_count > 0 ? model.total_latency_ms / model.call_count : 0;
}

/**
 * The model runtime. Every row is a role rather than a product name, because
 * what matters operationally is which capability is resident, what it is costing
 * and whether it has started failing.
 */
export function ModelsDivision() {
  const session = useSession();
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: queryKeys.models,
    queryFn: ({ signal }) => getModelRuntime(signal),
    refetchInterval: POLL_INTERVAL_MS.models,
  });

  const unload = useMutation({
    mutationFn: (role: string) => unloadModelRole(role),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.models }),
  });

  const runtime = query.data;

  return (
    <Division>
      <DivisionIntro
        title="Models"
        lede="Which capability is loaded, on what hardware, at what cost. A role that cannot load says why, and every investigation that needed it is marked degraded."
      />

      {query.isPending && (
        <Leaf>
          <LeafHead title="Loading runtime" />
          <SkeletonRows rows={5} />
        </Leaf>
      )}

      {query.isError && (
        <ErrorState error={query.error} context="Model runtime" onRetry={() => query.refetch()} />
      )}

      {runtime && (
        <div className="flex flex-col gap-3">
          <GpuCard runtime={runtime} />

          {unload.isError && <ErrorState error={unload.error} context="Unloading a role" />}

          <Leaf>
            <LeafHead
              title="Roles"
              count={runtime.models.length}
              hint={`${runtime.resident_roles.length} resident`}
            />
            {runtime.models.length === 0 ? (
              <EmptyState
                title="No model roles registered"
                body="The runtime reports no roles at all. Check the model configuration in settings."
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[56rem] text-mark">
                  <thead>
                    <tr className="border-b border-rule-strong">
                      {['Role', 'State', 'Runtime', 'Model', 'Device', 'VRAM', 'Calls', 'Avg latency', 'Errors', ''].map(
                        (heading) => (
                          <th
                            key={heading}
                            scope="col"
                            className={cn(
                              'px-3 py-1.5 text-left text-micro font-semibold uppercase tracking-[0.08em] text-ink-2',
                              ['VRAM', 'Calls', 'Avg latency', 'Errors'].includes(heading) && 'text-right',
                            )}
                          >
                            {heading}
                          </th>
                        ),
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {runtime.models.map((model) => (
                      <tr key={model.role} className="border-b border-rule last:border-b-0">
                        <td className="px-3 py-1.5">
                          <span className="block text-ink">{model.role}</span>
                          <span className="block text-micro text-ink-2">
                            {model.purpose || MODEL_ROLE_PURPOSE[model.role] || ''}
                          </span>
                        </td>
                        <td className="px-3 py-1.5">
                          <StatusChip tone={MODEL_STATE_TONE[model.state]}>
                            {MODEL_STATE_LABEL[model.state]}
                          </StatusChip>
                          {model.degraded && (
                            <span className="mt-0.5 block text-micro text-caution">
                              {model.degraded_reason ?? 'degraded'}
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-1.5 font-mono text-micro text-ink-1">
                          {model.active_runtime ?? '—'}
                        </td>
                        <td className="px-3 py-1.5 font-mono text-micro text-ink-1">
                          {model.active_model ?? '—'}
                        </td>
                        <td className="px-3 py-1.5 font-mono text-micro text-ink-1">
                          {model.device ?? '—'}
                        </td>
                        <td className="px-3 py-1.5 text-right font-mono tabular text-ink-1">
                          {model.vram_mb > 0 ? formatMegabytes(model.vram_mb) : '—'}
                        </td>
                        <td className="px-3 py-1.5 text-right font-mono tabular text-ink-1">
                          {model.call_count}
                        </td>
                        <td className="px-3 py-1.5 text-right font-mono tabular text-ink-1">
                          {formatLatency(averageLatency(model))}
                        </td>
                        <td
                          className={cn(
                            'px-3 py-1.5 text-right font-mono tabular',
                            model.error_count > 0 ? 'text-stamp font-semibold' : 'text-ink-1',
                          )}
                        >
                          {model.error_count}
                        </td>
                        <td className="px-3 py-1.5 text-right">
                          {session.can('manage_models') && model.state === 'loaded' && (
                            <Button
                              size="sm"
                              variant="secondary"
                              onClick={() => unload.mutate(model.role)}
                              disabled={unload.isPending}
                            >
                              Unload
                            </Button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {runtime.models.some((model) => model.last_error || model.candidates.length > 0) && (
              <Disclosure summary="Candidate runtimes and last errors">
                <ul className="flex flex-col">
                  {runtime.models.map((model) => (
                    <li key={model.role} className="border-b border-rule px-3 py-2 last:border-b-0">
                      <p className="text-mark font-semibold text-ink">{model.role}</p>
                      {model.last_error && (
                        <p className="mt-0.5 text-mark text-stamp">{model.last_error}</p>
                      )}
                      <ul className="mt-1 flex flex-col gap-0.5">
                        {model.candidates.map((candidate) => (
                          <li
                            key={`${candidate.runtime}-${candidate.model}`}
                            className="flex flex-wrap items-center gap-2 text-micro"
                          >
                            <span className="font-mono text-ink-1">
                              {candidate.runtime} · {candidate.model}
                            </span>
                            <span className="font-mono tabular text-ink-2">
                              {formatMegabytes(candidate.vram_mb)} · {candidate.device}
                            </span>
                            {candidate.available === false && (
                              <span className="text-caution">
                                unavailable — {candidate.unavailable_reason ?? 'no reason given'}
                              </span>
                            )}
                          </li>
                        ))}
                      </ul>
                    </li>
                  ))}
                </ul>
              </Disclosure>
            )}
          </Leaf>

          <Leaf>
            <LeafHead title="Load and unload events" count={runtime.recent_events.length} />
            {runtime.recent_events.length === 0 ? (
              <EmptyState
                title="No events recorded"
                body="Nothing has loaded or unloaded since the runtime started."
              />
            ) : (
              <ol className="flex flex-col">
                {[...runtime.recent_events].reverse().map((event, index) => (
                  <li
                    key={`${event.at}-${event.role}-${index}`}
                    className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 border-b border-rule px-3 py-1 last:border-b-0"
                  >
                    <time dateTime={event.at} className="font-mono text-micro tabular text-ink-2">
                      {formatRelative(event.at)}
                    </time>
                    <Mark>{event.role}</Mark>
                    <span className="text-mark font-semibold text-ink">{event.event}</span>
                    {event.vram_mb > 0 && (
                      <span className="font-mono text-micro tabular text-ink-2">
                        {formatMegabytes(event.vram_mb)}
                      </span>
                    )}
                    {event.detail && <span className="text-mark text-ink-1">{event.detail}</span>}
                  </li>
                ))}
              </ol>
            )}
          </Leaf>
        </div>
      )}
    </Division>
  );
}
