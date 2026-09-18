'use client';

import { useQuery } from '@tanstack/react-query';

import { getHealth } from '@/lib/api';
import { POLL_INTERVAL_MS, queryKeys } from '@/lib/query-keys';

/**
 * Health is polled, not assumed. Every screen that depends on the API can ask
 * this hook whether the service is reachable, and the answer is shown rather
 * than swallowed — a console that hides a dead backend is worse than no console.
 */
export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: ({ signal }) => getHealth(signal),
    refetchInterval: POLL_INTERVAL_MS.health,
    refetchOnWindowFocus: true,
    retry: 1,
    staleTime: 5_000,
  });
}
