'use client';

import { Gauge } from '@/components/meter';
import { InfoPopover } from '@/components/overlays';
import { Rule } from '@/components/leaf';
import { formatScore } from '@/lib/format';
import type { ScoreBreakdown } from '@/lib/schemas/primitives';

interface SignalRow {
  readonly key: keyof ScoreBreakdown;
  readonly label: string;
  readonly explanation: string;
}

const SIGNALS: readonly SignalRow[] = [
  { key: 'lexical', label: 'Lexical', explanation: 'Term overlap with the query.' },
  { key: 'semantic', label: 'Semantic', explanation: 'Vector similarity in the embedding index.' },
  { key: 'rerank', label: 'Rerank', explanation: 'Cross-encoder score. Null when rerank was off.' },
  { key: 'entity_match', label: 'Entity', explanation: 'A resolved entity in the query appears here.' },
  { key: 'metadata_match', label: 'Metadata', explanation: 'Filters, modality and time-window alignment.' },
  {
    key: 'source_reliability',
    label: 'Reliability',
    explanation: 'How much this source is trusted, independent of this query.',
  },
  { key: 'freshness', label: 'Freshness', explanation: 'How recent the underlying record is.' },
];

/**
 * Ranking is inspectable by design: SPECTRA does not rank on raw cosine
 * similarity, so the breakdown shows each signal separately rather than one
 * opaque relevance number.
 */
export function ScorePopover({ scores, score }: { scores: ScoreBreakdown; score: number }) {
  return (
    <InfoPopover
      label="Score breakdown"
      align="end"
      trigger={
        <button
          type="button"
          className="inline-flex items-center gap-1 rounded-sm border border-rule-strong bg-board-sunk px-1.5 py-[0.0625rem] font-mono text-micro tabular text-ink-1 hover:border-ink-3 hover:text-ink"
        >
          {formatScore(score)}
          <span className="text-ink-2">▾</span>
        </button>
      }
    >
      <p className="text-micro font-semibold uppercase tracking-[0.1em] text-ink-1">
        Score breakdown
      </p>
      <p className="mt-1 text-micro text-ink-2">
        Final {formatScore(scores.final)} — combined from the signals below, not from vector
        similarity alone.
      </p>
      <Rule className="my-2" />
      <dl className="flex flex-col gap-2">
        {SIGNALS.map((signal) => {
          const raw = scores[signal.key];
          const value = typeof raw === 'number' ? raw : null;
          return (
            <div key={signal.key} className="flex flex-col gap-0.5">
              <div className="flex items-baseline justify-between gap-2">
                <dt className="text-mark text-ink">{signal.label}</dt>
                <dd className="font-mono text-mark tabular text-ink-1">
                  {value === null ? 'not used' : formatScore(value, 3)}
                </dd>
              </div>
              {value !== null && <Gauge value={value} compact tone="held" />}
              <p className="text-micro text-ink-2">{signal.explanation}</p>
            </div>
          );
        })}
      </dl>
    </InfoPopover>
  );
}
