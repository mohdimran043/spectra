'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { getUploadJob, uploadFile } from '@/lib/api';
import { toSpectraError, type SpectraApiError } from '@/lib/api-error';
import { POLL_INTERVAL_MS } from '@/lib/query-keys';
import type { IngestJob } from '@/lib/schemas/system';

export interface UploadEntry {
  readonly localId: string;
  readonly fileName: string;
  readonly sizeBytes: number;
  readonly job: IngestJob | null;
  readonly error: SpectraApiError | null;
}

const TERMINAL_STATUSES = new Set(['ready', 'failed']);

let localIdCounter = 0;
const nextLocalId = () => `upl_${(localIdCounter += 1)}_${Date.now().toString(36)}`;

/**
 * Uploads are tracked to completion, not fired and forgotten. Each entry keeps
 * polling `GET /api/uploads/{job_id}` until the job reaches `ready` or `failed`,
 * and a failure keeps its reason on screen instead of vanishing.
 */
export function useUploadQueue() {
  const [entries, setEntries] = useState<readonly UploadEntry[]>([]);
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    const pending = timers.current;
    return () => {
      mounted.current = false;
      pending.forEach((timer) => clearTimeout(timer));
      pending.clear();
    };
  }, []);

  const patch = useCallback((localId: string, changes: Partial<UploadEntry>) => {
    if (!mounted.current) return;
    setEntries((current) =>
      current.map((entry) => (entry.localId === localId ? { ...entry, ...changes } : entry)),
    );
  }, []);

  const poll = useCallback(
    (localId: string, jobId: string) => {
      const run = async () => {
        try {
          const job = await getUploadJob(jobId);
          patch(localId, { job, error: null });
          if (!TERMINAL_STATUSES.has(job.status) && mounted.current) {
            timers.current.set(localId, setTimeout(run, POLL_INTERVAL_MS.uploadJob));
          }
        } catch (cause) {
          patch(localId, { error: toSpectraError(cause, `Upload job ${jobId}`) });
        }
      };
      timers.current.set(localId, setTimeout(run, POLL_INTERVAL_MS.uploadJob));
    },
    [patch],
  );

  const enqueue = useCallback(
    async (files: readonly File[]) => {
      for (const file of files) {
        const localId = nextLocalId();
        setEntries((current) => [
          ...current,
          { localId, fileName: file.name, sizeBytes: file.size, job: null, error: null },
        ]);
        try {
          const job = await uploadFile(file);
          patch(localId, { job });
          if (!TERMINAL_STATUSES.has(job.status)) poll(localId, job.job_id);
        } catch (cause) {
          patch(localId, { error: toSpectraError(cause, `Uploading ${file.name}`) });
        }
      }
    },
    [patch, poll],
  );

  const dismiss = useCallback((localId: string) => {
    const timer = timers.current.get(localId);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(localId);
    }
    setEntries((current) => current.filter((entry) => entry.localId !== localId));
  }, []);

  const readyAssetIds = entries
    .map((entry) => (entry.job?.status === 'ready' ? entry.job.asset_id : null))
    .filter((value): value is string => Boolean(value));

  return { entries, enqueue, dismiss, readyAssetIds };
}
