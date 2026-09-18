'use client';

import { useMemo, useState } from 'react';

import { Mark, StatusChip } from '@/components/chip';
import { cn } from '@/components/cn';
import { IconEye } from '@/components/icons';
import { Leaf, LeafHead } from '@/components/leaf';
import { ScaleMark } from '@/components/meter';
import { Tooltip } from '@/components/overlays';
import { EmptyState } from '@/components/states';
import { ExhibitStamp } from '@/components/stamp';
import { formatScore, splitId } from '@/lib/format';
import type { EvidenceItem } from '@/lib/schemas/evidence';
import type { EvidenceStance } from '@/lib/schemas/primitives';
import { STANCE_LABEL, STANCE_TONE } from '@/lib/vocab';
import { useExplorer } from '@/features/evidence/explorer-context';

type StanceFilter = EvidenceStance | 'all';

const STANCE_FILTERS: readonly StanceFilter[] = ['all', 'supporting', 'contradicting', 'neutral'];

/**
 * The evidence ledger: every exhibit the investigation used, with the citation
 * string, the stance it takes, how relevant it is, how reliable its source is
 * AND why — the reliability score never ships without its reason.
 */
export function EvidenceLedger({
  evidence,
  filterIds,
  filterLabel,
  onClearFilter,
  className,
}: {
  evidence: readonly EvidenceItem[];
  filterIds?: readonly string[] | null;
  filterLabel?: string | null;
  onClearFilter?: () => void;
  className?: string;
}) {
  const explorer = useExplorer();
  const [stance, setStance] = useState<StanceFilter>('all');

  const visible = useMemo(() => {
    const idSet = filterIds && filterIds.length > 0 ? new Set(filterIds) : null;
    return evidence
      .filter((item) => (idSet ? idSet.has(item.evidence_id) : true))
      .filter((item) => (stance === 'all' ? true : item.stance === stance))
      .sort((a, b) => b.relevance * b.reliability - a.relevance * a.reliability);
  }, [evidence, filterIds, stance]);

  const counts = useMemo(
    () => ({
      supporting: evidence.filter((item) => item.stance === 'supporting').length,
      contradicting: evidence.filter((item) => item.stance === 'contradicting').length,
      neutral: evidence.filter((item) => item.stance === 'neutral').length,
    }),
    [evidence],
  );

  return (
    <Leaf className={cn('flex min-h-0 flex-col', className)}>
      <LeafHead
        title="Evidence ledger"
        count={evidence.length}
        actions={
          <div className="flex flex-wrap items-center gap-1">
            {STANCE_FILTERS.map((candidate) => (
              <button
                key={candidate}
                type="button"
                aria-pressed={stance === candidate}
                onClick={() => setStance(candidate)}
                className={cn(
                  'rounded-sm border px-1.5 py-[0.0625rem] text-micro uppercase tracking-[0.07em]',
                  stance === candidate
                    ? 'border-ink bg-ink text-ink-inverse'
                    : 'border-rule-strong text-ink-1 hover:text-ink',
                )}
              >
                {candidate === 'all'
                  ? `All ${evidence.length}`
                  : `${STANCE_LABEL[candidate]} ${counts[candidate]}`}
              </button>
            ))}
          </div>
        }
      />

      {filterIds && filterIds.length > 0 && (
        <div className="flex items-center gap-2 border-b border-rule bg-held-weak px-3 py-1">
          <span className="text-micro uppercase tracking-[0.08em] text-held">
            Filtered to {filterLabel ?? 'selection'} · {filterIds.length}
          </span>
          {onClearFilter && (
            <button
              type="button"
              onClick={onClearFilter}
              className="ml-auto text-micro uppercase tracking-[0.08em] text-ink-2 underline decoration-rule-strong underline-offset-2 hover:text-ink"
            >
              Clear
            </button>
          )}
        </div>
      )}

      {visible.length === 0 ? (
        <EmptyState
          title={evidence.length === 0 ? 'No evidence recorded' : 'Nothing matches this filter'}
          body={
            evidence.length === 0
              ? 'Nothing reaches the answer without an exhibit. When the agents retrieve and accept an item, it is recorded here with its provenance.'
              : 'Clear the stance filter or the timeline selection to see the full ledger.'
          }
        />
      ) : (
        <ul className="min-h-0 flex-1 overflow-y-auto">
          {visible.map((item) => (
            <li key={item.evidence_id} className="border-b border-rule px-3 py-2.5 last:border-b-0">
              <div className="flex flex-wrap items-center gap-2">
                <ExhibitStamp
                  modality={item.modality}
                  reference={splitId(item.evidence_id).body.slice(0, 8)}
                  label={item.evidence_id}
                />
                <StatusChip tone={STANCE_TONE[item.stance]}>{STANCE_LABEL[item.stance]}</StatusChip>
                {item.retrieved_by && <Mark>{item.retrieved_by}</Mark>}
                <button
                  type="button"
                  onClick={() =>
                    explorer.open({
                      title: item.summary || item.evidence_id,
                      provenance: item.provenance,
                      excerpt: item.excerpt,
                      citation: item.citation,
                    })
                  }
                  className="ml-auto inline-flex items-center gap-1.5 text-micro uppercase tracking-[0.08em] text-ink-2 underline decoration-rule-strong underline-offset-2 hover:text-ink hover:decoration-ink"
                >
                  <IconEye size={12} />
                  Open provenance
                </button>
              </div>

              <p className="mt-1 text-body text-ink">{item.summary}</p>
              {item.excerpt && (
                <blockquote className="mt-1 border-l border-rule-strong pl-2.5 text-mark text-ink-1">
                  {item.excerpt}
                </blockquote>
              )}

              <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1">
                <span className="font-mono text-micro text-ink-2">
                  {item.citation ?? item.provenance.object_uri}
                </span>

                <span className="flex items-center gap-1.5">
                  <span className="text-micro uppercase tracking-[0.08em] text-ink-2">
                    Relevance
                  </span>
                  <ScaleMark value={item.relevance} tone="held" title={formatScore(item.relevance)} />
                  <span className="font-mono text-micro tabular text-ink-1">
                    {formatScore(item.relevance)}
                  </span>
                </span>

                <Tooltip
                  trigger={
                    <span className="flex cursor-help items-center gap-1.5">
                      <span className="text-micro uppercase tracking-[0.08em] text-ink-2">
                        Reliability
                      </span>
                      <ScaleMark
                        value={item.reliability}
                        tone={item.reliability >= 0.7 ? 'seal' : item.reliability >= 0.4 ? 'caution' : 'stamp'}
                      />
                      <span className="font-mono text-micro tabular text-ink-1 underline decoration-dotted decoration-ink-3 underline-offset-2">
                        {formatScore(item.reliability)}
                      </span>
                    </span>
                  }
                >
                  {item.reliability_reason ||
                    'No reliability reason was recorded for this source. Treat the score as unexplained.'}
                </Tooltip>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Leaf>
  );
}
