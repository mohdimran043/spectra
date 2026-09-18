'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useCallback, useState, type ReactNode } from 'react';

import { TooltipProvider } from '@/components/overlays';
import { SpectraApiError } from '@/lib/api-error';
import { ExplorerProvider } from '@/features/evidence/explorer-context';
import { SessionProvider } from '@/features/shell/session-context';

const RETRY_LIMIT = 2;

function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => {
          if (error instanceof SpectraApiError) {
            return error.isRetryable && failureCount < RETRY_LIMIT;
          }
          return failureCount < 1;
        },
      },
      mutations: { retry: false },
    },
  });
}

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(makeQueryClient);

  /** A role change changes what the API will return, so the cache is dropped. */
  const onRoleChange = useCallback(() => {
    queryClient.clear();
  }, [queryClient]);

  return (
    <QueryClientProvider client={queryClient}>
      <SessionProvider onRoleChange={onRoleChange}>
        <TooltipProvider>
          <ExplorerProvider>{children}</ExplorerProvider>
        </TooltipProvider>
      </SessionProvider>
    </QueryClientProvider>
  );
}
