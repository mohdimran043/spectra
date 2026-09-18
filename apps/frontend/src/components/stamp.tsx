import type { ReactNode } from 'react';

import type { Modality } from '@/lib/schemas/primitives';
import { MODALITY_LABEL, MODALITY_VAR } from '@/lib/vocab';
import { cn } from './cn';
import {
  IconAudio,
  IconDatabase,
  IconDocument,
  IconExternalSource,
  IconGraph,
  IconImage,
  IconVideo,
  type IconProps,
} from './icons';

const MODALITY_ICON: Record<Modality, (props: IconProps) => ReactNode> = {
  document: IconDocument,
  image: IconImage,
  video: IconVideo,
  audio: IconAudio,
  database: IconDatabase,
  graph: IconGraph,
  external: IconExternalSource,
};

export function ModalityGlyph({
  modality,
  size = 14,
  className,
}: {
  modality: Modality;
  size?: number;
  className?: string;
}) {
  const Glyph = MODALITY_ICON[modality];
  return (
    <span
      className={cn('inline-flex', className)}
      style={{ color: `var(${MODALITY_VAR[modality]})` }}
    >
      <Glyph size={size} />
    </span>
  );
}

/**
 * The exhibit stamp. Every retrievable unit in SPECTRA enters the record as an
 * exhibit: a struck box carrying its modality glyph and its short reference.
 * This is the product's one ornament, and it is always load-bearing — the
 * reference it prints is the id the operator can cite.
 */
export function ExhibitStamp({
  modality,
  reference,
  label,
  className,
}: {
  modality: Modality;
  reference: string;
  label?: string;
  className?: string;
}) {
  const hue = `var(${MODALITY_VAR[modality]})`;
  return (
    <span
      className={cn(
        'inline-flex select-none items-center gap-1.5 rounded-sm border px-1.5 py-0.5',
        className,
      )}
      style={{ borderColor: hue, color: hue }}
      title={`${MODALITY_LABEL[modality]} · ${label ?? reference}`}
    >
      <ModalityGlyph modality={modality} size={12} />
      <span className="font-mono text-micro font-semibold uppercase tracking-[0.08em]">
        {reference}
      </span>
    </span>
  );
}

/** Modality label + glyph, used in filters and tab strips. */
export function ModalityTag({
  modality,
  className,
}: {
  modality: Modality;
  className?: string;
}) {
  return (
    <span className={cn('inline-flex items-center gap-1.5 text-mark', className)}>
      <ModalityGlyph modality={modality} />
      <span>{MODALITY_LABEL[modality]}</span>
    </span>
  );
}
