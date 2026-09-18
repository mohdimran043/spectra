'use client';

import { useEffect } from 'react';

import { Button } from '@/components/button';
import { Leaf, LeafHead } from '@/components/leaf';
import { Division } from '@/components/page';
import { ErrorState } from '@/components/states';

export default function DivisionError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Client-side failures are reported to the console so a developer can see
    // the stack; the operator gets the readable message below.
    console.error('SPECTRA console error', error);
  }, [error]);

  return (
    <Division width="reading">
      <Leaf>
        <LeafHead title="This division failed to render" />
        <ErrorState error={error} context="Rendering the division" onRetry={reset} />
        <div className="px-3 pb-3">
          <Button variant="secondary" onClick={reset}>
            Try again
          </Button>
        </div>
      </Leaf>
    </Division>
  );
}
