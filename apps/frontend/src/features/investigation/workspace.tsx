'use client';

import { useState } from 'react';

import { Division } from '@/components/page';
import { DegradedBand, ErrorState, LoadingRule } from '@/components/states';
import { Leaf, LeafHead } from '@/components/leaf';
import { EmptyState } from '@/components/states';
import type { TimelineEvent } from '@/lib/schemas/evidence';
import { useExplorer } from '@/features/evidence/explorer-context';
import { GraphExplorer } from '@/features/graph/graph-explorer';
import { BrainStatus } from './brain-status';
import { ClaimsPanel } from './claims-panel';
import { Conclusion } from './conclusion';
import { ContradictionRadar } from './contradiction-radar';
import { EvidenceLedger } from './evidence-ledger';
import { QuestionHeader } from './question-header';
import { TimelinePanel } from './timeline-panel';
import { TracePanel } from './trace-panel';
import { useInvestigationRecord } from './use-investigation-record';

interface LedgerFilter {
  readonly ids: readonly string[];
  readonly label: string;
}

/**
 * The investigation workspace, in the order a case file is read: the question,
 * what the machine is doing, what conflicts were found, the claims and the
 * probes run against them, the connections, the chronology, the exhibits, and
 * only then the conclusion.
 */
export function InvestigationWorkspace({ investigationId }: { investigationId: string }) {
  const record = useInvestigationRecord(investigationId);
  const explorer = useExplorer();
  const [selectedEvent, setSelectedEvent] = useState<TimelineEvent | null>(null);
  const [ledgerFilter, setLedgerFilter] = useState<LedgerFilter | null>(null);

  const { stream, answer } = record;

  const activeFilter: LedgerFilter | null = selectedEvent
    ? { ids: selectedEvent.evidence_ids, label: selectedEvent.label }
    : ledgerFilter;

  const clearFilter = () => {
    setSelectedEvent(null);
    setLedgerFilter(null);
  };

  const showAnswerError =
    !answer && !stream.isLive && record.answerError !== null && record.answerError !== undefined;

  return (
    <Division>
      <div className="flex flex-col gap-3">
        <QuestionHeader
          investigationId={investigationId}
          question={record.question}
          caseId={record.caseId}
          mode={record.mode}
          hasConclusion={Boolean(answer)}
        />

        <BrainStatus
          connection={stream.connection}
          status={stream.status}
          iteration={stream.iteration}
          budget={stream.budget}
          lastHeartbeatAt={stream.lastHeartbeatAt}
          attempts={stream.attempts}
        />

        {stream.streamError && (
          <div
            className={`border px-3 py-2 ${
              stream.recoverable ? 'border-caution bg-caution-weak' : 'border-stamp bg-stamp-weak'
            }`}
            role="alert"
          >
            <p
              className={`text-micro font-semibold uppercase tracking-[0.1em] ${
                stream.recoverable ? 'text-caution' : 'text-stamp'
              }`}
            >
              {stream.recoverable ? 'Stream warning' : 'Stream error'}
            </p>
            <p className="mt-0.5 text-body text-ink">{stream.streamError}</p>
          </div>
        )}

        {answer?.degraded && <DegradedBand reasons={answer.degraded_reasons} />}

        {answer && (
          <ContradictionRadar
            contradictions={answer.contradictions}
            onOpenEvidence={(evidenceId) => explorer.openEvidenceId(evidenceId)}
          />
        )}

        <div className="grid gap-3 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)] xl:items-start">
          <ClaimsPanel
            claims={record.claims}
            live={stream.isLive}
            onSelectEvidence={(ids, label) => {
              setSelectedEvent(null);
              setLedgerFilter({ ids, label });
            }}
            className="max-h-[38rem]"
          />
          <TracePanel steps={record.trace} live={stream.isLive} className="max-h-[38rem]" />
        </div>

        <div className="grid gap-3 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)] xl:items-start">
          {record.graph ? (
            <GraphExplorer
              nodes={record.graph.nodes}
              edges={record.graph.edges}
              truncated={record.graph.truncated}
              height={420}
            />
          ) : (
            <Leaf>
              <LeafHead title="Evidence graph" />
              {record.graphError ? (
                <ErrorState error={record.graphError} context="Investigation graph" />
              ) : (
                <LoadingRule label="Building the graph" />
              )}
            </Leaf>
          )}

          <TimelinePanel
            events={answer?.timeline ?? []}
            selectedEventId={selectedEvent?.event_id ?? null}
            onSelect={(event) => {
              setLedgerFilter(null);
              setSelectedEvent(event);
            }}
            className="max-h-[32rem]"
          />
        </div>

        <EvidenceLedger
          evidence={record.evidence}
          filterIds={activeFilter?.ids ?? null}
          filterLabel={activeFilter?.label ?? null}
          onClearFilter={activeFilter ? clearFilter : undefined}
          className="max-h-[44rem]"
        />

        <div id="conclusion" className="scroll-mt-16">
          {answer ? (
            <Conclusion answer={answer} />
          ) : showAnswerError ? (
            <ErrorState
              error={record.answerError}
              context="Loading the conclusion"
            />
          ) : stream.isLive ? (
            <Leaf>
              <LeafHead title="Conclusion" />
              <LoadingRule label="The investigation is still running" />
              <EmptyState
                title="No conclusion yet"
                body="SPECTRA states a conclusion only after each claim has been weighed against its evidence and searched for its disproof. Until then this space stays empty rather than showing a draft."
              />
            </Leaf>
          ) : (
            <Leaf>
              <LeafHead title="Conclusion" />
              {record.isLoadingAnswer ? (
                <LoadingRule label="Loading the stored answer" />
              ) : (
                <EmptyState
                  title="No stored answer"
                  body="The API has no completed answer for this investigation id."
                />
              )}
            </Leaf>
          )}
        </div>
      </div>
    </Division>
  );
}
