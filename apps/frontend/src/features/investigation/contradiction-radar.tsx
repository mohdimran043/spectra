'use client';

import { Gauge } from '@/components/meter';
import { IconWarning } from '@/components/icons';
import { Rule } from '@/components/leaf';
import type { Contradiction } from '@/lib/schemas/evidence';
import { humaniseKey } from '@/lib/vocab';

/**
 * The contradiction radar.
 *
 * A conflict is never collapsed, never summarised away and never resolved
 * silently. The band states what the conflict is, which two exhibits disagree,
 * how severe it is, and either how it was resolved or that it was not — because
 * an investigation product that hides its contradictions is worse than one that
 * finds none.
 */
export function ContradictionRadar({
  contradictions,
  onOpenEvidence,
}: {
  contradictions: readonly Contradiction[];
  onOpenEvidence?: (evidenceId: string) => void;
}) {
  if (contradictions.length === 0) return null;

  return (
    <section
      aria-labelledby="contradiction-radar-heading"
      className="border border-stamp bg-stamp-weak"
    >
      <div className="flex flex-wrap items-center gap-2 border-b border-stamp/40 px-3 py-2">
        <IconWarning size={15} className="text-stamp" />
        <h2
          id="contradiction-radar-heading"
          className="text-mark font-semibold uppercase tracking-[0.14em] text-stamp"
        >
          Contradiction detected
        </h2>
        <span className="font-mono text-micro tabular text-stamp">
          {contradictions.length} {contradictions.length === 1 ? 'conflict' : 'conflicts'}
        </span>
      </div>

      <ul className="flex flex-col">
        {contradictions.map((contradiction) => (
          <li
            key={contradiction.contradiction_id}
            className="border-b border-stamp/25 px-3 py-2.5 last:border-b-0"
          >
            <p className="text-prose font-semibold text-ink">{contradiction.statement}</p>

            {contradiction.detail && (
              <p className="mt-1 text-body text-ink-1">{contradiction.detail}</p>
            )}

            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2">
              <div className="flex items-center gap-2">
                <span className="text-micro uppercase tracking-[0.08em] text-ink-2">Between</span>
                {[contradiction.evidence_a, contradiction.evidence_b].map((evidenceId) => (
                  <button
                    key={evidenceId}
                    type="button"
                    onClick={() => onOpenEvidence?.(evidenceId)}
                    disabled={!onOpenEvidence}
                    className="rounded-sm border border-stamp/50 bg-leaf px-1.5 py-[0.0625rem] font-mono text-micro tabular text-ink hover:border-stamp disabled:cursor-default"
                  >
                    {evidenceId}
                  </button>
                ))}
              </div>
              <span className="text-micro uppercase tracking-[0.08em] text-ink-2">
                {humaniseKey(contradiction.kind)}
              </span>
              <div className="w-32">
                <Gauge
                  value={contradiction.severity}
                  tone="stamp"
                  compact
                  label="Severity"
                  reading={contradiction.severity.toFixed(2)}
                />
              </div>
            </div>

            <Rule className="my-2 border-stamp/25" />

            <div className="flex flex-col gap-1">
              <span className="text-micro font-semibold uppercase tracking-[0.08em] text-ink-1">
                Resolution
              </span>
              {contradiction.resolution ? (
                <p className="text-body text-ink">
                  {contradiction.resolution}
                  {contradiction.resolved_in_favour_of && (
                    <span className="ml-1 font-mono text-micro tabular text-ink-2">
                      (in favour of {contradiction.resolved_in_favour_of})
                    </span>
                  )}
                </p>
              ) : (
                <p className="text-body text-stamp">
                  Unresolved. Both readings are still on the record and the conclusion below is
                  weighted accordingly.
                </p>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
