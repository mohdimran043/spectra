'use client';

import { StatusChip } from '@/components/chip';
import { cn } from '@/components/cn';
import { IconCheck, IconDisproof } from '@/components/icons';
import { Gauge } from '@/components/meter';
import { Tooltip } from '@/components/overlays';
import { formatPercent } from '@/lib/format';
import type { Claim } from '@/lib/schemas/evidence';
import { CLAIM_STATUS_LABEL, CLAIM_STATUS_MEANING, CLAIM_STATUS_TONE } from '@/lib/vocab';

const REFUTING_STATUSES: ReadonlySet<Claim['status']> = new Set(['refuted', 'contradicted']);

const NO_PROBE_RECORDED =
  'No disproof probe was recorded for this claim. Nothing was searched for that would overturn it, so treat the confidence as untested.';

/**
 * What the disproof search actually did, stated in the past tense. The point is
 * not that a probe exists — it is whether SPECTRA went out and looked for it,
 * and what came back.
 */
function probeOutcome(claim: Claim): string {
  if (!claim.disproof_searched) {
    return 'SPECTRA has not run this search yet. Nothing has challenged the claim.';
  }
  return REFUTING_STATUSES.has(claim.status)
    ? 'SPECTRA searched for it — and found it. See the contradicting exhibits.'
    : 'SPECTRA searched for it and did not find it.';
}

/**
 * An absolute confidence reading.
 *
 * The axis is printed with both of its ends so the bar can only be read as
 * "this far along 0–100%", never as this claim's slice of some shared total.
 * Claims are scored one at a time against their own evidence; two claims can
 * both sit at 90% and neither is taking anything from the other.
 */
function ClaimConfidence({ claim }: { claim: Claim }) {
  const tone = CLAIM_STATUS_TONE[claim.status];
  return (
    <div className="flex flex-col gap-1">
      <Gauge
        value={claim.confidence}
        tone={tone}
        label="Confidence in this claim"
        reading={formatPercent(claim.confidence, 0)}
      />
      <div
        className="flex items-baseline justify-between font-mono text-micro tabular text-ink-2"
        aria-hidden="true"
      >
        <span>0%</span>
        <span className="normal-case tracking-normal">judged on its own evidence</span>
        <span>100%</span>
      </div>
    </div>
  );
}

function EvidenceLink({
  count,
  kind,
  onOpen,
}: {
  count: number;
  kind: 'supporting' | 'contradicting';
  onOpen: () => void;
}) {
  const supporting = kind === 'supporting';
  return (
    <button
      type="button"
      onClick={onOpen}
      className={cn(
        'rounded-sm text-micro uppercase tracking-[0.08em] underline underline-offset-2',
        'focus-visible:outline focus-visible:outline-1 focus-visible:outline-offset-2',
        supporting
          ? 'text-seal decoration-seal/50 hover:decoration-seal focus-visible:outline-seal'
          : 'text-stamp decoration-stamp/50 hover:decoration-stamp focus-visible:outline-stamp',
      )}
    >
      Show {count} {kind} in ledger
    </button>
  );
}

/** One claim: the statement, how well it stands, and what was done to break it. */
export function ClaimCard({
  claim,
  onSelectEvidence,
}: {
  claim: Claim;
  onSelectEvidence?: (evidenceIds: readonly string[], label: string) => void;
}) {
  const supporting = claim.supporting_evidence.length;
  const contradicting = claim.contradicting_evidence.length;

  return (
    <li className="border-b border-rule px-3 py-2.5 last:border-b-0">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="font-mono text-mark font-semibold tabular text-ink-2">
          {claim.claim_id}
        </span>
        <Tooltip
          trigger={
            <span>
              <StatusChip tone={CLAIM_STATUS_TONE[claim.status]}>
                {CLAIM_STATUS_LABEL[claim.status]}
              </StatusChip>
            </span>
          }
        >
          {CLAIM_STATUS_MEANING[claim.status]}
        </Tooltip>
        {claim.verified && (
          <StatusChip tone="seal" icon={<IconCheck size={10} />}>
            Verified
          </StatusChip>
        )}
        {!claim.disproof_searched && <StatusChip tone="caution">Unchallenged</StatusChip>}
      </div>

      <p className="mt-1 max-w-[72ch] text-prose text-ink">{claim.text}</p>
      {claim.rationale && <p className="mt-1 text-mark text-ink-2">{claim.rationale}</p>}

      <div className="mt-2 grid gap-2 md:grid-cols-[minmax(0,15rem)_minmax(0,1fr)] md:items-start">
        <ClaimConfidence claim={claim} />

        <div className="flex flex-col gap-1.5">
          <div
            className={cn(
              'border px-2 py-1.5',
              claim.disproof_searched ? 'border-rule bg-board-sunk' : 'border-caution bg-caution-weak',
            )}
          >
            <p className="flex items-center gap-1.5 text-micro font-semibold uppercase tracking-[0.08em] text-ink-1">
              <IconDisproof size={11} />
              Disproof probe — what would break this claim
            </p>
            <p className="mt-0.5 text-mark text-ink">{claim.disproof_probe ?? NO_PROBE_RECORDED}</p>
            {claim.disproof_probe && (
              <p
                className={cn(
                  'mt-1 text-micro',
                  claim.disproof_searched ? 'text-ink-2' : 'text-caution',
                )}
              >
                {probeOutcome(claim)}
              </p>
            )}
          </div>

          {claim.verification_note && (
            <p className="text-mark text-ink-2">{claim.verification_note}</p>
          )}

          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-micro text-ink-2">
            <span className="tabular">
              <span className="text-seal">{supporting}</span> supporting
            </span>
            <span className="tabular">
              <span className={contradicting > 0 ? 'font-semibold text-stamp' : ''}>
                {contradicting}
              </span>{' '}
              contradicting
            </span>
          </div>

          {onSelectEvidence && supporting + contradicting > 0 && (
            <div className="flex flex-wrap gap-x-3 gap-y-1">
              {supporting > 0 && (
                <EvidenceLink
                  count={supporting}
                  kind="supporting"
                  onOpen={() =>
                    onSelectEvidence(claim.supporting_evidence, `${claim.claim_id} supporting`)
                  }
                />
              )}
              {contradicting > 0 && (
                <EvidenceLink
                  count={contradicting}
                  kind="contradicting"
                  onOpen={() =>
                    onSelectEvidence(
                      claim.contradicting_evidence,
                      `${claim.claim_id} contradicting`,
                    )
                  }
                />
              )}
            </div>
          )}
        </div>
      </div>
    </li>
  );
}
