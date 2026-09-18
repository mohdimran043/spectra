'use client';

import { useQuery } from '@tanstack/react-query';
import { useEffect, useMemo } from 'react';

import {
  getInvestigation,
  getInvestigationGraph,
  getInvestigationTrace,
  listInvestigations,
} from '@/lib/api';
import { queryKeys } from '@/lib/query-keys';
import type { TraceStep } from '@/lib/schemas/investigation';
import { useInvestigationStream } from './use-investigation-stream';

function mergeTrace(
  streamed: readonly TraceStep[],
  replayed: readonly TraceStep[],
): TraceStep[] {
  const bySequence = new Map<string, TraceStep>();
  for (const step of replayed) bySequence.set(step.step_id, step);
  for (const step of streamed) bySequence.set(step.step_id, step);
  return [...bySequence.values()].sort((a, b) => a.sequence - b.sequence);
}

/**
 * One record, assembled from three places: the live stream, the stored answer,
 * and the replayable trace. The stream leads while it is open; once it closes
 * the stored answer is refetched, so a page opened after the fact shows exactly
 * what a page opened during the run ends up showing.
 */
export function useInvestigationRecord(investigationId: string) {
  const stream = useInvestigationStream(investigationId);

  const answerQuery = useQuery({
    queryKey: queryKeys.investigation(investigationId),
    queryFn: ({ signal }) => getInvestigation(investigationId, signal),
    retry: false,
    staleTime: 30_000,
  });

  const traceQuery = useQuery({
    queryKey: queryKeys.investigationTrace(investigationId),
    queryFn: ({ signal }) => getInvestigationTrace(investigationId, signal),
    retry: false,
    enabled: !stream.isLive,
  });

  const graphQuery = useQuery({
    queryKey: queryKeys.investigationGraph(investigationId),
    queryFn: ({ signal }) => getInvestigationGraph(investigationId, signal),
    retry: false,
  });

  /** `InvestigationAnswer` carries no question text; the summary rows do. */
  const summaryQuery = useQuery({
    queryKey: queryKeys.investigations,
    queryFn: ({ signal }) => listInvestigations(signal),
    retry: false,
  });

  const { connection } = stream;
  const { refetch: refetchAnswer } = answerQuery;
  const { refetch: refetchGraph } = graphQuery;

  useEffect(() => {
    if (connection === 'closed') {
      void refetchAnswer();
      void refetchGraph();
    }
  }, [connection, refetchAnswer, refetchGraph]);

  const answer = stream.answer ?? answerQuery.data ?? null;

  const trace = useMemo(
    () => mergeTrace(stream.trace, traceQuery.data ?? []),
    [stream.trace, traceQuery.data],
  );

  const hypotheses = stream.hypotheses.length > 0 ? stream.hypotheses : (answer?.hypotheses ?? []);
  const evidence = stream.evidence.length > 0 ? stream.evidence : (answer?.evidence ?? []);

  const summary = (summaryQuery.data ?? []).find(
    (row) => row.investigation_id === investigationId,
  );

  return {
    stream,
    answer,
    trace,
    hypotheses,
    evidence,
    graph: graphQuery.data ?? null,
    graphError: graphQuery.error,
    answerError: answerQuery.error,
    isLoadingAnswer: answerQuery.isPending,
    question: summary?.question ?? summary?.goal ?? null,
    caseId: summary?.case_id ?? null,
    mode: summary?.mode ?? null,
  };
}
