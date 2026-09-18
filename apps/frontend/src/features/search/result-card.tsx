'use client';

import { cn } from '@/components/cn';
import { assetContentUrl, assetThumbnailUrl } from '@/lib/api';
import { formatTimecode, splitId } from '@/lib/format';
import type { SearchHit } from '@/lib/schemas/search';
import { MODALITY_LABEL, MODALITY_VAR } from '@/lib/vocab';

import { Snippet } from './snippet';

/**
 * One result.
 *
 * A row, not a card: results are a ranked list and a list should read as one.
 * The rank number anchors it, the snippet is the content, and everything else -
 * where it came from, how it scored - sits quietly underneath where it can be
 * checked but never competes with the text.
 */
export function ResultCard({ hit, rank }: { hit: SearchHit; rank: number }) {
  const where = locationOf(hit);
  const visual = hit.modality === 'image' || hit.modality === 'video';

  return (
    <li className="border-b border-rule last:border-b-0">
      <a
        href={assetContentUrl(hit.asset_id)}
        target="_blank"
        rel="noreferrer"
        className={cn(
          'flex gap-4 rounded-sm px-2 py-4 transition-colors',
          'hover:bg-leaf-raised focus-visible:bg-leaf-raised',
          'focus-visible:outline focus-visible:outline-1 focus-visible:outline-offset-2 focus-visible:outline-focus',
        )}
      >
        <span
          aria-hidden="true"
          className="mt-px w-5 shrink-0 text-right font-mono text-mark tabular text-ink-3"
        >
          {rank}
        </span>

        <span className="min-w-0 flex-1">
          <span className="mb-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1">
            <span
              className="text-micro font-semibold uppercase tracking-[0.07em]"
              style={{ color: `var(${MODALITY_VAR[hit.modality]})` }}
            >
              {MODALITY_LABEL[hit.modality]}
            </span>
            {hit.title && (
              <span className="truncate text-mark font-medium text-ink-1">{hit.title}</span>
            )}
          </span>

          <Snippet text={hit.snippet || hit.text} clamp={3} className="max-w-[70ch]" />

          <span className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-micro text-ink-2">
            <span className="font-mono tabular" title="Relevance score">
              {hit.score.toFixed(3)}
            </span>
            {where && <span className="truncate">{where}</span>}
            <span className="truncate text-ink-3">{splitId(hit.source_id).body}</span>
          </span>
        </span>

        {visual && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={assetThumbnailUrl(hit.asset_id)}
            alt=""
            loading="lazy"
            className="hidden h-16 w-24 shrink-0 border border-rule bg-board-sunk object-cover sm:block"
            onError={(event) => {
              event.currentTarget.style.visibility = 'hidden';
            }}
          />
        )}
      </a>
    </li>
  );
}

/** Where in the source this passage sits, in that modality's own language. */
function locationOf(hit: SearchHit): string | null {
  const locator = hit.provenance?.locator as Record<string, unknown> | undefined;
  if (!locator) return null;
  if (typeof locator.page === 'number') return `page ${locator.page}`;
  if (typeof locator.start_seconds === 'number') return formatTimecode(locator.start_seconds);
  if (typeof locator.record_id === 'string' && locator.record_id) return locator.record_id;
  return null;
}
