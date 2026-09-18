'use client';

import { useCallback, useEffect, useReducer, useRef } from 'react';

import { buildAuthHeaders, investigationStreamUrl } from '@/lib/api';
import { readEventStream, type ServerSentEvent } from '@/lib/sse';
import type { Claim, EvidenceItem } from '@/lib/schemas/evidence';
import {
  investigationAnswerSchema,
  streamClaimsFrameSchema,
  streamErrorFrameSchema,
  streamEvidenceFrameSchema,
  streamStatusFrameSchema,
  traceStepSchema,
  type BudgetState,
  type InvestigationAnswer,
  type TraceStep,
} from '@/lib/schemas/investigation';

export type ConnectionState = 'idle' | 'connecting' | 'open' | 'closed' | 'failed';

export interface StreamState {
  readonly connection: ConnectionState;
  readonly trace: readonly TraceStep[];
  readonly claims: readonly Claim[];
  readonly evidence: readonly EvidenceItem[];
  readonly status: string | null;
  readonly iteration: number | null;
  readonly budget: BudgetState | null;
  readonly answer: InvestigationAnswer | null;
  /** A stream-level failure, kept visible rather than retried into silence. */
  readonly streamError: string | null;
  readonly recoverable: boolean;
  readonly lastEventId: string | null;
  readonly lastHeartbeatAt: number | null;
  readonly attempts: number;
}

type Action =
  | { type: 'connecting' }
  | { type: 'open' }
  | { type: 'heartbeat' }
  | { type: 'trace'; step: TraceStep; id: string | null }
  | { type: 'claims'; claims: Claim[]; id: string | null }
  | { type: 'evidence'; evidence: EvidenceItem[]; id: string | null }
  | { type: 'status'; status: string; iteration: number | null; budget: BudgetState | null; id: string | null }
  | { type: 'complete'; answer: InvestigationAnswer; id: string | null }
  | { type: 'stream-error'; message: string; recoverable: boolean }
  | { type: 'closed' }
  | { type: 'failed'; message: string }
  | { type: 'reset' };

const INITIAL_STATE: StreamState = {
  connection: 'idle',
  trace: [],
  claims: [],
  evidence: [],
  status: null,
  iteration: null,
  budget: null,
  answer: null,
  streamError: null,
  recoverable: false,
  lastEventId: null,
  lastHeartbeatAt: null,
  attempts: 0,
};

/** Trace steps are keyed by step id and ordered by sequence; replays overwrite. */
function mergeTrace(current: readonly TraceStep[], incoming: TraceStep): TraceStep[] {
  const next = current.filter((step) => step.step_id !== incoming.step_id);
  next.push(incoming);
  return next.sort((a, b) => a.sequence - b.sequence);
}

function mergeEvidence(
  current: readonly EvidenceItem[],
  incoming: readonly EvidenceItem[],
): EvidenceItem[] {
  const byId = new Map(current.map((item) => [item.evidence_id, item]));
  for (const item of incoming) byId.set(item.evidence_id, item);
  return [...byId.values()];
}

function reducer(state: StreamState, action: Action): StreamState {
  switch (action.type) {
    case 'reset':
      return INITIAL_STATE;
    case 'connecting':
      return { ...state, connection: 'connecting', attempts: state.attempts + 1, streamError: null };
    case 'open':
      return { ...state, connection: 'open', lastHeartbeatAt: Date.now() };
    case 'heartbeat':
      return { ...state, lastHeartbeatAt: Date.now() };
    case 'trace':
      return {
        ...state,
        trace: mergeTrace(state.trace, action.step),
        lastEventId: action.id ?? state.lastEventId,
      };
    case 'claims':
      return { ...state, claims: action.claims, lastEventId: action.id ?? state.lastEventId };
    case 'evidence':
      return {
        ...state,
        evidence: mergeEvidence(state.evidence, action.evidence),
        lastEventId: action.id ?? state.lastEventId,
      };
    case 'status':
      return {
        ...state,
        status: action.status,
        iteration: action.iteration,
        budget: action.budget ?? state.budget,
        lastEventId: action.id ?? state.lastEventId,
      };
    case 'complete':
      return {
        ...state,
        answer: action.answer,
        claims: action.answer.claims.length > 0 ? action.answer.claims : state.claims,
        evidence: mergeEvidence(state.evidence, action.answer.evidence),
        status: 'completed',
        connection: 'closed',
        lastEventId: action.id ?? state.lastEventId,
      };
    case 'stream-error':
      return { ...state, streamError: action.message, recoverable: action.recoverable };
    case 'closed':
      return { ...state, connection: 'closed' };
    case 'failed':
      return { ...state, connection: 'failed', streamError: action.message };
    default:
      return state;
  }
}

const MAX_RECONNECT_ATTEMPTS = 6;
const BASE_BACKOFF_MS = 800;
const MAX_BACKOFF_MS = 15_000;

function backoffFor(attempt: number): number {
  return Math.min(BASE_BACKOFF_MS * 2 ** Math.max(0, attempt - 1), MAX_BACKOFF_MS);
}

/**
 * The investigation stream.
 *
 * Connects to `GET /api/stream/investigation/{id}`, resumes with
 * `Last-Event-ID` after a drop, tolerates the 15-second heartbeat, gives up
 * loudly after a bounded number of attempts, and aborts cleanly on unmount. It
 * never invents a step: everything it holds came off the wire and was parsed
 * through the contract schemas first.
 */
export function useInvestigationStream(investigationId: string | null, enabled = true) {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);
  const abortRef = useRef<AbortController | null>(null);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastEventIdRef = useRef<string | null>(null);
  const attemptRef = useRef(0);
  const stoppedRef = useRef(false);

  const handleEvent = useCallback((event: ServerSentEvent) => {
    let payload: unknown;
    try {
      payload = JSON.parse(event.data);
    } catch {
      dispatch({
        type: 'stream-error',
        message: `A ${event.event} frame arrived with a body that is not JSON and was discarded.`,
        recoverable: true,
      });
      return;
    }
    if (event.id) lastEventIdRef.current = event.id;

    switch (event.event) {
      case 'trace': {
        const parsed = traceStepSchema.safeParse(payload);
        if (parsed.success) dispatch({ type: 'trace', step: parsed.data, id: event.id });
        else
          dispatch({
            type: 'stream-error',
            message: `A trace frame did not match the contract (${parsed.error.issues[0]?.message ?? 'unknown field'}) and was discarded.`,
            recoverable: true,
          });
        return;
      }
      case 'claims': {
        const parsed = streamClaimsFrameSchema.safeParse(payload);
        if (parsed.success) dispatch({ type: 'claims', claims: parsed.data.claims, id: event.id });
        return;
      }
      case 'evidence': {
        const parsed = streamEvidenceFrameSchema.safeParse(payload);
        if (parsed.success)
          dispatch({ type: 'evidence', evidence: parsed.data.evidence, id: event.id });
        return;
      }
      case 'status': {
        const parsed = streamStatusFrameSchema.safeParse(payload);
        if (parsed.success)
          dispatch({
            type: 'status',
            status: parsed.data.status,
            iteration: parsed.data.iteration ?? null,
            budget: parsed.data.budget ?? null,
            id: event.id,
          });
        return;
      }
      case 'complete': {
        const parsed = investigationAnswerSchema.safeParse(payload);
        if (parsed.success) {
          stoppedRef.current = true;
          dispatch({ type: 'complete', answer: parsed.data, id: event.id });
          abortRef.current?.abort();
        } else {
          dispatch({
            type: 'stream-error',
            message: `The completed answer did not match the contract (${parsed.error.issues[0]?.path.join('.') ?? 'root'}: ${parsed.error.issues[0]?.message ?? 'unknown'}). Reload the investigation to fetch it directly.`,
            recoverable: false,
          });
        }
        return;
      }
      case 'error': {
        const parsed = streamErrorFrameSchema.safeParse(payload);
        const message = parsed.success ? parsed.data.error : 'The investigation reported an error.';
        const recoverable = parsed.success ? parsed.data.recoverable : false;
        if (!recoverable) stoppedRef.current = true;
        dispatch({ type: 'stream-error', message, recoverable });
        if (!recoverable) abortRef.current?.abort();
        return;
      }
      default:
        /* Unknown event names are ignored: the contract may add frames. */
        return;
    }
  }, []);

  const connect = useCallback(() => {
    if (!investigationId || stoppedRef.current) return;

    const controller = new AbortController();
    abortRef.current = controller;
    attemptRef.current += 1;
    dispatch({ type: 'connecting' });

    readEventStream(investigationStreamUrl(investigationId), {
      headers: buildAuthHeaders(),
      signal: controller.signal,
      lastEventId: lastEventIdRef.current,
      handlers: {
        onOpen: () => {
          attemptRef.current = 0;
          dispatch({ type: 'open' });
        },
        onHeartbeat: () => dispatch({ type: 'heartbeat' }),
        onEvent: handleEvent,
      },
    })
      .then(() => {
        if (stoppedRef.current || controller.signal.aborted) return;
        /* A clean end without `complete` means the server closed the stream. */
        dispatch({ type: 'closed' });
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted || stoppedRef.current) return;
        const message = cause instanceof Error ? cause.message : String(cause);
        if (attemptRef.current >= MAX_RECONNECT_ATTEMPTS) {
          dispatch({
            type: 'failed',
            message: `The investigation stream dropped and could not be resumed after ${MAX_RECONNECT_ATTEMPTS} attempts (${message}). The completed record can still be loaded from the API.`,
          });
          return;
        }
        retryTimer.current = setTimeout(connect, backoffFor(attemptRef.current));
      });
  }, [investigationId, handleEvent]);

  useEffect(() => {
    if (!investigationId || !enabled) return undefined;

    stoppedRef.current = false;
    attemptRef.current = 0;
    lastEventIdRef.current = null;
    dispatch({ type: 'reset' });
    connect();

    return () => {
      stoppedRef.current = true;
      abortRef.current?.abort();
      if (retryTimer.current) clearTimeout(retryTimer.current);
    };
  }, [investigationId, enabled, connect]);

  const isLive = state.connection === 'connecting' || state.connection === 'open';

  return { ...state, isLive };
}
