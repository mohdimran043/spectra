'use client';

import { Leaf, LeafHead } from '@/components/leaf';
import { formatLatency } from '@/lib/format';
import type { SearchResponse } from '@/lib/schemas/search';
import { humaniseKey } from '@/lib/vocab';

/**
 * The retrieval pipeline, stage by stage, with what went in and what came out.
 * This is the search equivalent of the investigation's trace: the operator can
 * see where the candidate pool collapsed and how long each stage cost.
 */
export function StageStrip({ response }: { response: SearchResponse }) {
  if (response.stages.length === 0) return null;

  const widest = Math.max(...response.stages.map((stage) => stage.candidates_out), 1);

  return (
    <Leaf>
      <LeafHead title="Retrieval stages" count={response.stages.length} />
      <ol className="flex flex-col">
        {response.stages.map((stage) => (
          <li
            key={stage.stage}
            className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-rule px-3 py-1.5 last:border-b-0"
          >
            <span className="w-44 shrink-0 text-mark text-ink">{humaniseKey(stage.stage)}</span>
            <span className="font-mono text-micro tabular text-ink-2">
              {stage.candidates_in} → {stage.candidates_out}
            </span>
            <span
              className="h-1.5 bg-held"
              style={{ width: `${Math.max(2, (stage.candidates_out / widest) * 100)}%`, maxWidth: '38%' }}
              aria-hidden="true"
            />
            <span className="ml-auto font-mono text-micro tabular text-ink-1">
              {formatLatency(stage.latency_ms)}
            </span>
            {stage.detail && <span className="w-full text-micro text-ink-2">{stage.detail}</span>}
          </li>
        ))}
      </ol>
    </Leaf>
  );
}
