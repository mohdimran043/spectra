'use client';

import { StatusChip } from '@/components/chip';
import { cn } from '@/components/cn';
import { IconCheck, IconDisproof } from '@/components/icons';
import { Leaf, LeafHead } from '@/components/leaf';
import { BalanceMeter } from '@/components/meter';
import { Tooltip } from '@/components/overlays';
import { EmptyState } from '@/components/states';
import type { Hypothesis } from '@/lib/schemas/evidence';
import {
  HYPOTHESIS_STATUS_LABEL,
  HYPOTHESIS_STATUS_MEANING,
  HYPOTHESIS_STATUS_TONE,
} from '@/lib/vocab';

/**
 * Competing explanations, each scored against the evidence that supports it AND
 * the evidence that would kill it. The disproof probe is shown in full: a
 * hypothesis nobody tried to falsify is a guess, and the operator needs to see
 * whether the attempt was made.
 */
export function HypothesesPanel({
  hypotheses,
  onSelectEvidence,
  className,
}: {
  hypotheses: readonly Hypothesis[];
  onSelectEvidence?: (evidenceIds: readonly string[], label: string) => void;
  className?: string;
}) {
  const ordered = [...hypotheses].sort((a, b) => b.confidence - a.confidence);

  return (
    <Leaf className={cn('flex min-h-0 flex-col', className)}>
      <LeafHead
        title="Hypotheses"
        count={hypotheses.length}
        hint={
          hypotheses.length > 0
            ? `${hypotheses.filter((h) => h.disproof_searched).length} disproof-probed`
            : undefined
        }
      />
      {ordered.length === 0 ? (
        <EmptyState
          title="No competing explanations yet"
          body="SPECTRA generates rival explanations before it commits to one. They appear here with their confidence, their supporting and contradicting evidence, and the probe that would disprove each."
        />
      ) : (
        <ul className="flex flex-col">
          {ordered.map((hypothesis) => {
            const supporting = hypothesis.supporting_evidence.length;
            const contradicting = hypothesis.contradicting_evidence.length;
            return (
              <li key={hypothesis.hypothesis_id} className="border-b border-rule px-3 py-2.5 last:border-b-0">
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="font-mono text-mark font-semibold tabular text-ink-2">
                    {hypothesis.hypothesis_id}
                  </span>
                  <Tooltip
                    trigger={
                      <span>
                        <StatusChip tone={HYPOTHESIS_STATUS_TONE[hypothesis.status]}>
                          {HYPOTHESIS_STATUS_LABEL[hypothesis.status]}
                        </StatusChip>
                      </span>
                    }
                  >
                    {HYPOTHESIS_STATUS_MEANING[hypothesis.status]}
                  </Tooltip>
                  {hypothesis.verified && (
                    <StatusChip tone="seal" icon={<IconCheck size={10} />}>
                      Verified
                    </StatusChip>
                  )}
                </div>

                <p className="mt-1 text-prose text-ink">{hypothesis.description}</p>
                {hypothesis.rationale && (
                  <p className="mt-1 text-mark text-ink-2">{hypothesis.rationale}</p>
                )}

                <div className="mt-2 grid gap-2 md:grid-cols-[minmax(0,15rem)_minmax(0,1fr)] md:items-start">
                  <BalanceMeter
                    value={hypothesis.confidence}
                    tone={HYPOTHESIS_STATUS_TONE[hypothesis.status]}
                    supporting={supporting}
                    contradicting={contradicting}
                    label="Confidence"
                  />

                  <div className="flex flex-col gap-1.5">
                    <div
                      className={cn(
                        'border px-2 py-1.5',
                        hypothesis.disproof_searched
                          ? 'border-rule bg-board-sunk'
                          : 'border-caution bg-caution-weak',
                      )}
                    >
                      <p className="flex items-center gap-1.5 text-micro font-semibold uppercase tracking-[0.08em] text-ink-1">
                        <IconDisproof size={11} />
                        Disproof probe
                        {!hypothesis.disproof_searched && (
                          <span className="font-normal normal-case tracking-normal text-caution">
                            not yet searched
                          </span>
                        )}
                      </p>
                      <p className="mt-0.5 text-mark text-ink">
                        {hypothesis.disproof_probe ??
                          'No probe was recorded for this hypothesis. Treat its confidence as untested.'}
                      </p>
                    </div>

                    {hypothesis.verification_note && (
                      <p className="text-mark text-ink-2">{hypothesis.verification_note}</p>
                    )}

                    {onSelectEvidence && supporting + contradicting > 0 && (
                      <div className="flex flex-wrap gap-2">
                        {supporting > 0 && (
                          <button
                            type="button"
                            onClick={() =>
                              onSelectEvidence(
                                hypothesis.supporting_evidence,
                                `${hypothesis.hypothesis_id} supporting`,
                              )
                            }
                            className="text-micro uppercase tracking-[0.08em] text-seal underline decoration-seal/50 underline-offset-2 hover:decoration-seal"
                          >
                            Show {supporting} supporting in ledger
                          </button>
                        )}
                        {contradicting > 0 && (
                          <button
                            type="button"
                            onClick={() =>
                              onSelectEvidence(
                                hypothesis.contradicting_evidence,
                                `${hypothesis.hypothesis_id} contradicting`,
                              )
                            }
                            className="text-micro uppercase tracking-[0.08em] text-stamp underline decoration-stamp/50 underline-offset-2 hover:decoration-stamp"
                          >
                            Show {contradicting} contradicting in ledger
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Leaf>
  );
}
