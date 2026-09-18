'use client';

import Link from 'next/link';

import { Mark } from '@/components/chip';
import { cn } from '@/components/cn';
import { IconEye, IconPlay } from '@/components/icons';
import { ExhibitStamp } from '@/components/stamp';
import { assetThumbnailUrl } from '@/lib/api';
import { formatDate, formatTimecode, formatTimecodeRange, splitId } from '@/lib/format';
import type { SearchHit } from '@/lib/schemas/search';
import { MODALITY_LABEL } from '@/lib/vocab';
import { useExplorer } from '@/features/evidence/explorer-context';
import { SegmentRail } from '@/features/evidence/media-players';
import { ScorePopover } from './score-popover';
import { Snippet } from './snippet';

function metadataString(hit: SearchHit, key: string): string | null {
  const value = hit.metadata[key];
  return typeof value === 'string' && value.trim() ? value : null;
}

function Thumbnail({ hit, alt }: { hit: SearchHit; alt: string }) {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={assetThumbnailUrl(hit.asset_id)}
      alt={alt}
      loading="lazy"
      className="h-[4.5rem] w-32 shrink-0 border border-rule bg-board-sunk object-cover"
      onError={(event) => {
        event.currentTarget.style.visibility = 'hidden';
      }}
    />
  );
}

/**
 * One hit, in its own modality's language. A document result reads like a page
 * reference, a video result reads like a cue, a database result reads like a
 * record — the layout does not flatten five retrieval modes into one card.
 */
export function ResultCard({ hit }: { hit: SearchHit }) {
  const explorer = useExplorer();
  const locator = hit.provenance.locator;
  const title = hit.title ?? splitId(hit.asset_id).body;

  const open = () =>
    explorer.open({
      title,
      provenance: hit.provenance,
      assetId: hit.asset_id,
      excerpt: hit.text || undefined,
      citation: hit.provenance.source_name ?? hit.source_id,
    });

  return (
    <article className="border-b border-rule px-3 py-3 last:border-b-0 hover:bg-board-sunk/40">
      <div className="flex flex-wrap items-center gap-2">
        <ExhibitStamp
          modality={hit.modality}
          reference={splitId(hit.chunk_id).body.slice(0, 8)}
          label={hit.chunk_id}
        />
        <button
          type="button"
          onClick={open}
          className="min-w-0 truncate text-left text-head font-semibold text-ink underline decoration-transparent underline-offset-2 hover:decoration-ink"
        >
          {title}
        </button>
        <div className="ml-auto flex items-center gap-2">
          <ScorePopover scores={hit.scores} score={hit.score} />
        </div>
      </div>

      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-micro text-ink-2">
        <span>{MODALITY_LABEL[hit.modality]}</span>
        <span className="font-mono">{hit.provenance.source_name ?? hit.source_id}</span>
        {locator.kind === 'document' && (
          <span className="font-mono tabular">
            {locator.page !== null && locator.page !== undefined ? `page ${locator.page}` : null}
            {locator.section ? ` · ${locator.section}` : ''}
          </span>
        )}
        {locator.kind === 'database' && (
          <span className="font-mono tabular">
            {locator.table}.{locator.primary_key}={locator.record_id}
          </span>
        )}
        {hit.occurred_at && <span>occurred {formatDate(hit.occurred_at)}</span>}
        <span className="font-mono">{hit.provenance.version_status}</span>
      </div>

      <div className="mt-2 flex flex-col gap-2">
        {/* Image and video results lead with the frame, then the words. */}
        {(hit.modality === 'image' || hit.modality === 'video') && (
          <div className="flex gap-3">
            <button type="button" onClick={open} className="shrink-0" aria-label={`Open ${title}`}>
              <Thumbnail hit={hit} alt={`Thumbnail of ${title}`} />
            </button>
            <div className="min-w-0 flex-1 flex-col gap-1.5">
              {hit.modality === 'video' && locator.kind === 'video' && (
                <button
                  type="button"
                  onClick={open}
                  className="mb-1 inline-flex items-center gap-1.5 rounded-sm border border-mod-video px-2 py-0.5 text-mark font-semibold text-mod-video hover:bg-board-sunk"
                >
                  <IconPlay size={11} />
                  Play from {formatTimecode(locator.start_seconds)}
                </button>
              )}
              <Snippet text={hit.snippet} clamp={3} />
              {metadataString(hit, 'caption') && (
                <p className="text-mark text-ink-1">
                  <span className="text-ink-2">Caption </span>
                  {metadataString(hit, 'caption')}
                </p>
              )}
              {metadataString(hit, 'ocr_text') && (
                <p className="text-mark text-ink-1">
                  <span className="text-ink-2">OCR </span>
                  {metadataString(hit, 'ocr_text')}
                </p>
              )}
              {metadataString(hit, 'visual_description') && (
                <p className="text-mark text-ink-1">
                  <span className="text-ink-2">Visual </span>
                  {metadataString(hit, 'visual_description')}
                </p>
              )}
            </div>
          </div>
        )}

        {hit.modality === 'audio' && locator.kind === 'audio' && (
          <div className="flex flex-col gap-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={open}
                className="inline-flex items-center gap-1.5 rounded-sm border border-mod-audio px-2 py-0.5 font-mono text-mark font-semibold tabular text-mod-audio hover:bg-board-sunk"
              >
                <IconPlay size={11} />
                {formatTimecodeRange(locator.start_seconds, locator.end_seconds)}
              </button>
              {locator.speaker && <Mark>{locator.speaker}</Mark>}
            </div>
            <SegmentRail
              startSeconds={locator.start_seconds}
              endSeconds={locator.end_seconds}
              className="max-w-md"
            />
            <Snippet text={hit.snippet} clamp={3} />
          </div>
        )}

        {(hit.modality === 'document' ||
          hit.modality === 'database' ||
          hit.modality === 'graph' ||
          hit.modality === 'external') && <Snippet text={hit.snippet} clamp={4} />}
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
        {hit.entities.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-micro uppercase tracking-[0.08em] text-ink-2">Entities</span>
            {hit.entities.slice(0, 6).map((entityId) => (
              <Link
                key={entityId}
                href={`/graph?focus=${encodeURIComponent(entityId)}`}
                className="rounded-sm border border-rule bg-board-sunk px-1.5 py-[0.0625rem] font-mono text-micro text-ink-1 hover:border-ink-3 hover:text-ink"
              >
                {entityId}
              </Link>
            ))}
            {hit.entities.length > 6 && (
              <span className="text-micro text-ink-2">+{hit.entities.length - 6}</span>
            )}
          </div>
        )}
        <button
          type="button"
          onClick={open}
          className={cn(
            'ml-auto inline-flex items-center gap-1.5 text-micro uppercase tracking-[0.08em] text-ink-2',
            'underline decoration-rule-strong underline-offset-2 hover:text-ink hover:decoration-ink',
          )}
        >
          <IconEye size={12} />
          Open provenance
        </button>
      </div>
    </article>
  );
}
