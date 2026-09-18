'use client';

import { useRouter } from 'next/navigation';
import { useRef, useState, type DragEvent } from 'react';

import { Button } from '@/components/button';
import { cn } from '@/components/cn';
import { IconClose, IconSearch, IconUpload } from '@/components/icons';
import { ModalityGlyph } from '@/components/stamp';
import { Gauge } from '@/components/meter';
import { formatBytes } from '@/lib/format';
import type { Modality } from '@/lib/schemas/primitives';
import { JOB_STAGES, JOB_STATUS_LABEL, MODALITY_VAR } from '@/lib/vocab';
import type { UploadEntry } from './use-upload-queue';

interface DropSpec {
  readonly modality: Extract<Modality, 'image' | 'audio' | 'video' | 'document'>;
  readonly label: string;
  readonly accept: string;
  readonly note: string;
}

const DROP_SPECS: readonly DropSpec[] = [
  { modality: 'image', label: 'Image', accept: 'image/*', note: 'OCR, caption, entity extraction' },
  { modality: 'audio', label: 'Audio', accept: 'audio/*', note: 'Transcript with speaker segments' },
  { modality: 'video', label: 'Video', accept: 'video/*', note: 'Scenes, frames, transcript' },
  {
    modality: 'document',
    label: 'Document',
    accept: '.pdf,.docx,.doc,.txt,.md,.csv,.xlsx,.pptx',
    note: 'Pages, sections, tables',
  },
];

function DropCell({
  spec,
  onFiles,
  disabled,
}: {
  spec: DropSpec;
  onFiles: (files: readonly File[]) => void;
  disabled: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setOver(false);
    if (disabled) return;
    const files = Array.from(event.dataTransfer.files);
    if (files.length > 0) onFiles(files);
  };

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        if (!disabled) setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={handleDrop}
      className={cn(
        'flex min-h-[5.25rem] flex-col justify-between border p-2.5 transition-colors duration-100 ease-step',
        over ? 'border-focus bg-held-weak' : 'border-rule bg-leaf',
        disabled && 'opacity-55',
      )}
    >
      <div className="flex items-start gap-2">
        <span style={{ color: `var(${MODALITY_VAR[spec.modality]})` }}>
          <ModalityGlyph modality={spec.modality} size={15} />
        </span>
        <div className="min-w-0">
          <p className="text-mark font-semibold text-ink">{spec.label}</p>
          <p className="text-micro text-ink-2">{spec.note}</p>
        </div>
      </div>
      <div className="mt-2 flex items-center justify-between gap-2">
        <span className="text-micro text-ink-2">Drop here</span>
        <Button
          size="sm"
          variant="secondary"
          disabled={disabled}
          onClick={() => inputRef.current?.click()}
        >
          <IconUpload size={11} />
          Browse
        </Button>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept={spec.accept}
        multiple
        className="sr-only"
        aria-label={`Upload ${spec.label.toLowerCase()} files`}
        disabled={disabled}
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          if (files.length > 0) onFiles(files);
          event.target.value = '';
        }}
      />
    </div>
  );
}

function StageRail({ entry }: { entry: UploadEntry }) {
  const status = entry.job?.status ?? 'queued';
  const reached = JOB_STAGES.indexOf(status);
  return (
    <ol className="flex flex-wrap items-center gap-1" aria-label="Ingestion stages">
      {JOB_STAGES.map((stage, index) => {
        const done = reached >= 0 && index <= reached;
        return (
          <li
            key={stage}
            className={cn(
              'rounded-sm border px-1 py-[0.0625rem] text-micro uppercase tracking-[0.06em]',
              done ? 'border-seal bg-seal-weak text-seal' : 'border-rule text-ink-2',
            )}
          >
            {JOB_STATUS_LABEL[stage]}
          </li>
        );
      })}
    </ol>
  );
}

/**
 * Image upload is a first-class interaction: once an image is ready it offers
 * the thing an investigator actually wants next, which is to search that image
 * across every source rather than merely to have stored it.
 */
export function UploadQueue({
  entries,
  onDismiss,
}: {
  entries: readonly UploadEntry[];
  onDismiss: (localId: string) => void;
}) {
  const router = useRouter();
  if (entries.length === 0) return null;

  return (
    <ul className="flex flex-col border-t border-rule">
      {entries.map((entry) => {
        const job = entry.job;
        const failed = job?.status === 'failed' || entry.error !== null;
        const ready = job?.status === 'ready';
        return (
          <li key={entry.localId} className="flex flex-col gap-1.5 border-b border-rule px-3 py-2">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className="truncate text-mark font-semibold text-ink">{entry.fileName}</span>
              <span className="font-mono text-micro tabular text-ink-2">
                {formatBytes(entry.sizeBytes)}
              </span>
              {job?.asset_id && (
                <span className="font-mono text-micro tabular text-ink-2">{job.asset_id}</span>
              )}
              <button
                type="button"
                onClick={() => onDismiss(entry.localId)}
                aria-label={`Dismiss ${entry.fileName}`}
                className="ml-auto rounded-sm p-0.5 text-ink-2 hover:text-ink"
              >
                <IconClose size={12} />
              </button>
            </div>

            {failed ? (
              <p className="text-mark text-stamp">
                {entry.error?.reason ?? job?.error ?? 'The ingestion job failed.'}
              </p>
            ) : (
              <>
                <StageRail entry={entry} />
                <Gauge value={job?.progress ?? 0} compact tone="held" />
                {job?.message && <p className="text-micro text-ink-2">{job.message}</p>}
              </>
            )}

            {ready && job?.asset_id && (
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() =>
                    router.push(`/search?tab=images&asset=${encodeURIComponent(job.asset_id ?? '')}`)
                  }
                >
                  <IconSearch size={11} />
                  Search this asset across SPECTRA
                </Button>
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

export function DropTargets({
  onFiles,
  disabled = false,
}: {
  onFiles: (files: readonly File[]) => void;
  disabled?: boolean;
}) {
  return (
    <div className="grid grid-cols-2 gap-2 xl:grid-cols-4">
      {DROP_SPECS.map((spec) => (
        <DropCell key={spec.modality} spec={spec} onFiles={onFiles} disabled={disabled} />
      ))}
    </div>
  );
}
