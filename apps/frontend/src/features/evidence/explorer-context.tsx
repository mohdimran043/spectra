'use client';

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';

import type { Provenance } from '@/lib/schemas/primitives';
import { ExplorerDrawer } from './explorer-drawer';

export interface ExplorerTarget {
  readonly title: string;
  readonly provenance: Provenance;
  /**
   * The asset the bytes live under. Search hits carry it directly; evidence
   * items do not, so the drawer falls back to the locator's own id.
   */
  readonly assetId?: string;
  readonly excerpt?: string;
  readonly citation?: string;
  /** Database rows arrive as fields rather than bytes. */
  readonly record?: Record<string, unknown>;
}

interface ExplorerValue {
  readonly open: (target: ExplorerTarget) => void;
  readonly openEvidenceId: (evidenceId: string) => void;
}

const ExplorerContext = createContext<ExplorerValue | null>(null);

/**
 * One explorer for the whole console. A citation in the evidence ledger, a hit
 * in search results and a node in the graph all open the same artefact at the
 * same coordinates, because "click through to the source" has to mean one thing.
 */
export function ExplorerProvider({ children }: { children: ReactNode }) {
  const [target, setTarget] = useState<ExplorerTarget | null>(null);
  const [evidenceId, setEvidenceId] = useState<string | null>(null);

  const open = useCallback((next: ExplorerTarget) => {
    setEvidenceId(null);
    setTarget(next);
  }, []);

  const openEvidenceId = useCallback((id: string) => {
    setTarget(null);
    setEvidenceId(id);
  }, []);

  const close = useCallback(() => {
    setTarget(null);
    setEvidenceId(null);
  }, []);

  const value = useMemo<ExplorerValue>(() => ({ open, openEvidenceId }), [open, openEvidenceId]);

  return (
    <ExplorerContext.Provider value={value}>
      {children}
      <ExplorerDrawer target={target} evidenceId={evidenceId} onClose={close} />
    </ExplorerContext.Provider>
  );
}

export function useExplorer(): ExplorerValue {
  const value = useContext(ExplorerContext);
  if (!value) throw new Error('useExplorer must be used inside ExplorerProvider');
  return value;
}
