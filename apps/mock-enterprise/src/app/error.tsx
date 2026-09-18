'use client';

import { useEffect } from 'react';

/** Last-resort boundary: a rendering failure still produces a readable page. */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error('[mock-enterprise] render error:', error.message, error.digest);
  }, [error]);

  return (
    <div role="alert" className="border border-red-700 bg-red-50 p-6 text-red-900">
      <h1 className="text-lg font-bold">This page could not be displayed</h1>
      <p className="mt-2">
        An unexpected error occurred while rendering enterprise records. No cached or sample
        data is shown in its place.
      </p>
      <button
        type="button"
        onClick={reset}
        className="mt-4 border border-red-700 bg-white px-3 py-1.5 text-xs font-semibold uppercase tracking-wide"
      >
        Try again
      </button>
    </div>
  );
}
