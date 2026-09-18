'use client';

import { cn } from '@/components/cn';
import { Leaf, LeafHead } from '@/components/leaf';
import { EmptyState, SkeletonRows } from '@/components/states';
import type { Claim } from '@/lib/schemas/evidence';
import { ClaimCard } from './claim-card';

function probedCount(claims: readonly Claim[]): number {
  return claims.filter((claim) => claim.disproof_searched).length;
}

/**
 * The claims the investigation is prepared to assert.
 *
 * Each claim stands on its own evidence, so this panel deliberately refuses the
 * leaderboard reading: the claims keep the order the record states them in
 * rather than being sorted by confidence, and each confidence is drawn on its
 * own 0–100% axis instead of sharing one bar. A single well-supported
 * conclusion therefore reads as one high figure, not as a 100% slice of
 * nothing.
 *
 * Alongside every claim is the probe SPECTRA went looking for in order to break
 * it, and whether that search actually ran — a claim nobody tried to falsify is
 * an assertion, not a finding.
 */
export function ClaimsPanel({
  claims,
  live = false,
  onSelectEvidence,
  className,
}: {
  claims: readonly Claim[];
  live?: boolean;
  onSelectEvidence?: (evidenceIds: readonly string[], label: string) => void;
  className?: string;
}) {
  const probed = probedCount(claims);
  const pending = live && claims.length === 0;

  return (
    <Leaf className={cn('flex min-h-0 flex-col', className)}>
      <LeafHead
        title="Claims"
        count={claims.length}
        hint={claims.length > 0 ? `${probed} disproof-probed` : undefined}
      />

      {/* The live region announces the count only, never the whole list again. */}
      <p aria-live="polite" aria-atomic="true" className="sr-only">
        {claims.length === 0
          ? 'No claims stated yet.'
          : `${claims.length} ${claims.length === 1 ? 'claim' : 'claims'} stated, ${probed} disproof-probed.`}
      </p>

      {claims.length > 0 && (
        <p className="border-b border-rule px-3 py-1.5 text-micro text-ink-2">
          Every claim is scored against its own evidence. These confidences are independent
          readings, not shares of one total, and they do not add up to 100%.
        </p>
      )}

      {pending ? (
        <SkeletonRows rows={2} />
      ) : claims.length === 0 ? (
        <EmptyState
          title="No claims stated yet"
          body="SPECTRA states a claim only once it has evidence for it and has searched for the evidence that would break it. Each claim appears here with its own confidence, the exhibits supporting it, and the disproof probe that was run against it."
        />
      ) : (
        <ul className="min-h-0 flex-1 overflow-y-auto">
          {claims.map((claim) => (
            <ClaimCard key={claim.claim_id} claim={claim} onSelectEvidence={onSelectEvidence} />
          ))}
        </ul>
      )}
    </Leaf>
  );
}
