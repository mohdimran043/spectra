'use client';

import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';

import { Mark } from '@/components/chip';
import { cn } from '@/components/cn';
import { IconLinkOut } from '@/components/icons';
import { Drawer } from '@/components/overlays';
import { Reading, Rule } from '@/components/leaf';
import { ErrorState, LoadingRule } from '@/components/states';
import { ModalityGlyph } from '@/components/stamp';
import { assetContentUrl, assetPageUrl, assetThumbnailUrl, getEvidence } from '@/lib/api';
import { formatDateTime } from '@/lib/format';
import { queryKeys } from '@/lib/query-keys';
import type { Locator, Provenance } from '@/lib/schemas/primitives';
import { MODALITY_LABEL } from '@/lib/vocab';
import { SeekedAudio, SeekedVideo, SegmentRail } from './media-players';
import type { ExplorerTarget } from './explorer-context';

/**
 * The contract gives no `asset_id` on `Provenance`, so a citation that does not
 * arrive alongside a search hit is opened through the locator's own identifier.
 * If that identifier is not the asset id in a given deployment, the asset route
 * 404s and the drawer says so rather than showing an empty frame.
 */
function resolveAssetId(target: ExplorerTarget): string | null {
  if (target.assetId) return target.assetId;
  const locator = target.provenance.locator;
  switch (locator.kind) {
    case 'document':
      return locator.document_id;
    case 'image':
      return locator.image_id;
    case 'video':
      return locator.video_id;
    case 'audio':
      return locator.audio_id;
    default:
      return null;
  }
}

function locatorReadings(locator: Locator) {
  switch (locator.kind) {
    case 'document':
      return [
        ['Document', locator.document_id],
        ['Page', locator.page ?? '—'],
        ['Section', locator.section ?? '—'],
        ['Paragraph', locator.paragraph ?? '—'],
      ] as const;
    case 'image':
      return [['Image', locator.image_id]] as const;
    case 'video':
      return [
        ['Video', locator.video_id],
        ['Scene', locator.scene_id ?? '—'],
        ['Frame', locator.frame_id ?? '—'],
      ] as const;
    case 'audio':
      return [
        ['Audio', locator.audio_id],
        ['Segment', locator.segment_id ?? '—'],
        ['Speaker', locator.speaker ?? '—'],
      ] as const;
    case 'database':
      return [
        ['Table', locator.table],
        ['Key', locator.primary_key],
        ['Record', locator.record_id],
        ['Column', locator.column ?? '—'],
      ] as const;
    case 'external':
      return [
        ['Resource', locator.resource],
        ['Record', locator.record_id ?? '—'],
      ] as const;
  }
}

function ArtefactFrame({ target }: { target: ExplorerTarget }) {
  const [imageFailed, setImageFailed] = useState(false);
  const assetId = resolveAssetId(target);
  const locator = target.provenance.locator;

  if (locator.kind === 'database') {
    const record = target.record ?? {};
    const keys = Object.keys(record);
    if (keys.length === 0) {
      return (
        <p className="text-body text-ink-2">
          The database record is cited as{' '}
          <span className="font-mono">
            {locator.table}.{locator.primary_key}={locator.record_id}
          </span>
          . Its field values are not carried on the citation; open it in the application below.
        </p>
      );
    }
    return (
      <table className="w-full border border-rule text-mark">
        <tbody>
          {keys.map((key) => (
            <tr key={key} className="border-b border-rule last:border-b-0">
              <th scope="row" className="w-1/3 border-r border-rule px-2 py-1 text-left font-medium text-ink-2">
                {key}
              </th>
              <td className="px-2 py-1 font-mono tabular text-ink">{String(record[key] ?? '—')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }

  if (!assetId) {
    return (
      <p className="text-body text-ink-2">
        This citation points at{' '}
        <span className="font-mono">{target.provenance.object_uri}</span>, which has no openable
        asset route on the API.
      </p>
    );
  }

  if (locator.kind === 'video') {
    return (
      <SeekedVideo
        src={assetContentUrl(assetId)}
        poster={assetThumbnailUrl(assetId)}
        startSeconds={locator.start_seconds}
        endSeconds={locator.end_seconds}
      />
    );
  }

  if (locator.kind === 'audio') {
    return (
      <div className="flex flex-col gap-2">
        <SegmentRail startSeconds={locator.start_seconds} endSeconds={locator.end_seconds} />
        <SeekedAudio
          src={assetContentUrl(assetId)}
          startSeconds={locator.start_seconds}
          endSeconds={locator.end_seconds}
          speaker={locator.speaker}
        />
      </div>
    );
  }

  const source =
    locator.kind === 'document' && locator.page
      ? assetPageUrl(assetId, locator.page)
      : assetContentUrl(assetId);

  if (imageFailed) {
    return (
      <p className="text-body text-stamp">
        The artefact at <span className="font-mono">{source}</span> could not be loaded. The asset
        may not be indexed yet, or this citation&rsquo;s identifier is not the asset id in this
        deployment.
      </p>
    );
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={source}
      alt={
        locator.kind === 'document'
          ? `Page ${locator.page} of document ${locator.document_id}`
          : `Image ${target.title}`
      }
      onError={() => setImageFailed(true)}
      className="max-h-[62vh] w-full border border-rule bg-board-sunk object-contain"
    />
  );
}

function ProvenanceBlock({ provenance }: { provenance: Provenance }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
        {locatorReadings(provenance.locator).map(([label, value]) => (
          <Reading key={label} label={label} value={String(value)} />
        ))}
      </div>
      <Rule />
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
        <Reading label="Source" value={provenance.source_name ?? provenance.source_id} mono={false} />
        <Reading label="Version" value={`${provenance.version ?? '—'} · ${provenance.version_status}`} />
        <Reading label="Created" value={formatDateTime(provenance.created_at)} />
        <Reading label="Ingested" value={formatDateTime(provenance.ingested_at)} />
      </div>
      <p className="break-all font-mono text-micro text-ink-2">{provenance.object_uri}</p>
    </div>
  );
}

export function ExplorerDrawer({
  target,
  evidenceId,
  onClose,
}: {
  target: ExplorerTarget | null;
  evidenceId: string | null;
  onClose: () => void;
}) {
  const evidenceQuery = useQuery({
    queryKey: queryKeys.evidence(evidenceId ?? ''),
    queryFn: ({ signal }) => getEvidence(evidenceId ?? '', signal),
    enabled: Boolean(evidenceId),
  });

  const resolved = useMemo<ExplorerTarget | null>(() => {
    if (target) return target;
    const item = evidenceQuery.data;
    if (!item) return null;
    return {
      title: item.summary || item.evidence_id,
      provenance: item.provenance,
      excerpt: item.excerpt,
      citation: item.citation,
    };
  }, [target, evidenceQuery.data]);

  const open = Boolean(target) || Boolean(evidenceId);

  return (
    <Drawer
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title={resolved?.title ?? 'Evidence'}
      description={resolved?.citation}
    >
      {evidenceId && evidenceQuery.isPending && <LoadingRule label="Resolving citation" />}
      {evidenceId && evidenceQuery.isError && (
        <ErrorState error={evidenceQuery.error} context="Evidence lookup" />
      )}
      {resolved && (
        <div className="flex flex-col gap-4 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <Mark>
              <ModalityGlyph modality={resolved.provenance.modality} size={11} />
              {MODALITY_LABEL[resolved.provenance.modality]}
            </Mark>
            {resolved.citation && (
              <span className="font-mono text-micro text-ink-1">{resolved.citation}</span>
            )}
          </div>

          <ArtefactFrame target={resolved} />

          {resolved.excerpt && (
            <blockquote className={cn('border-l border-rule-strong pl-3 text-prose text-ink')}>
              {resolved.excerpt}
            </blockquote>
          )}

          <ProvenanceBlock provenance={resolved.provenance} />

          {resolveAssetId(resolved) && resolved.provenance.locator.kind !== 'database' && (
            <a
              href={assetContentUrl(resolveAssetId(resolved) ?? '')}
              target="_blank"
              rel="noreferrer"
              className="inline-flex w-fit items-center gap-1.5 text-mark text-ink-1 underline decoration-rule-strong underline-offset-2 hover:text-ink"
            >
              <IconLinkOut size={12} />
              Open the raw asset
            </a>
          )}
        </div>
      )}
    </Drawer>
  );
}
