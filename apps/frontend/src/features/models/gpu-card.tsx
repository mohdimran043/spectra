'use client';

import { Mark, StatusChip } from '@/components/chip';
import { IconGpu, IconWarning } from '@/components/icons';
import { Leaf, LeafHead, Reading, Rule } from '@/components/leaf';
import { Gauge } from '@/components/meter';
import { formatMegabytes, formatPercent } from '@/lib/format';
import type { GpuStatus, ModelRuntimeStatus } from '@/lib/schemas/system';
import { MODEL_ROLE_PURPOSE } from '@/lib/vocab';

/**
 * The unavailable state is informative, not broken.
 *
 * This machine has no usable GPU: the API reports why in `gpu.detail`, and that
 * text is the most useful thing on the screen. It gets the headline, followed by
 * what still works without one.
 */
function GpuUnavailable({ gpu, runtime }: { gpu: GpuStatus; runtime: ModelRuntimeStatus }) {
  return (
    <Leaf>
      <LeafHead
        title="GPU"
        actions={<StatusChip tone="caution">Unavailable</StatusChip>}
      />
      <div className="flex flex-col gap-3 p-3">
        <div className="flex items-start gap-3 border border-caution bg-caution-weak p-3">
          <IconWarning size={16} className="mt-0.5 shrink-0 text-caution" />
          <div className="min-w-0">
            <p className="text-head font-semibold text-ink">
              No usable GPU is available to this deployment
            </p>
            <p className="mt-1 max-w-[70ch] text-body text-ink-1">
              {gpu.detail ??
                'The runtime reported no accelerator. No further detail was supplied by the API.'}
            </p>
            {gpu.driver_version && (
              <p className="mt-1 font-mono text-micro tabular text-ink-2">
                driver {gpu.driver_version}
                {gpu.name ? ` · device reported as ${gpu.name}` : ''}
              </p>
            )}
          </div>
        </div>

        <div>
          <p className="text-micro font-semibold uppercase tracking-[0.08em] text-ink-1">
            What still runs
          </p>
          <p className="mt-1 max-w-[74ch] text-body text-ink-2">
            Lexical retrieval, the embedded vector index, entity resolution, the knowledge graph and
            the database path do not need an accelerator. Roles that do will report{' '}
            <span className="font-mono">unavailable</span> in the table below with the reason they
            could not load, and investigations that touch them will come back marked degraded rather
            than silently weaker.
          </p>
        </div>

        {runtime.degraded_reasons.length > 0 && (
          <>
            <Rule />
            <ul className="flex flex-col gap-0.5">
              {runtime.degraded_reasons.map((reason) => (
                <li key={reason} className="text-mark text-caution">
                  {reason}
                </li>
              ))}
            </ul>
          </>
        )}

        <Rule />
        <div className="flex flex-wrap gap-x-6 gap-y-2">
          <Reading label="Profile" value={runtime.profile} mono={false} />
          <Reading label="Queue depth" value={String(runtime.queue_depth)} />
          <Reading
            label="Active role"
            value={runtime.active_role ? MODEL_ROLE_PURPOSE[runtime.active_role] ?? runtime.active_role : 'idle'}
            mono={false}
          />
          <Reading label="Resident roles" value={String(runtime.resident_roles.length)} />
        </div>
      </div>
    </Leaf>
  );
}

export function GpuCard({ runtime }: { runtime: ModelRuntimeStatus }) {
  const gpu = runtime.gpu;
  if (!gpu.available) return <GpuUnavailable gpu={gpu} runtime={runtime} />;

  const usedRatio = gpu.total_mb > 0 ? gpu.used_mb / gpu.total_mb : 0;

  return (
    <Leaf>
      <LeafHead
        title="GPU"
        actions={
          <>
            <StatusChip tone={runtime.degraded ? 'caution' : 'seal'}>
              {runtime.degraded ? 'Degraded' : 'Available'}
            </StatusChip>
            <Mark>{runtime.profile}</Mark>
          </>
        }
      />
      <div className="flex flex-col gap-3 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <IconGpu size={18} className="text-ink-1" />
          <span className="text-title font-semibold text-ink">{gpu.name ?? 'Accelerator'}</span>
          {gpu.driver_version && <Mark mono>driver {gpu.driver_version}</Mark>}
        </div>

        <Gauge
          value={gpu.used_mb}
          max={gpu.total_mb}
          tone={usedRatio > 0.9 ? 'stamp' : usedRatio > 0.7 ? 'caution' : 'seal'}
          label="VRAM"
          reading={`${formatMegabytes(gpu.used_mb)} / ${formatMegabytes(gpu.total_mb)}`}
        />

        <div className="flex flex-wrap gap-x-6 gap-y-2">
          <Reading label="Free" value={formatMegabytes(gpu.free_mb)} />
          <Reading label="Budget" value={formatMegabytes(gpu.budget_mb)} />
          <Reading
            label="Utilisation"
            value={gpu.utilisation_pct === null ? '—' : formatPercent(gpu.utilisation_pct / 100, 0)}
          />
          <Reading
            label="Temperature"
            value={gpu.temperature_c === null || gpu.temperature_c === undefined ? '—' : `${gpu.temperature_c} °C`}
          />
          <Reading label="Queue depth" value={String(runtime.queue_depth)} />
          <Reading
            label="Active role"
            value={runtime.active_role ?? 'idle'}
          />
        </div>

        {gpu.detail && <p className="text-mark text-ink-2">{gpu.detail}</p>}

        {runtime.degraded_reasons.length > 0 && (
          <ul className="flex flex-col gap-0.5 border-t border-rule pt-2">
            {runtime.degraded_reasons.map((reason) => (
              <li key={reason} className="text-mark text-caution">
                {reason}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Leaf>
  );
}
