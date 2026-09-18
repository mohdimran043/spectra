import type { StatusTone } from '@/lib/vocab';

/**
 * A tone is a status, not a decoration. Each one resolves to one ink colour and
 * one wash, both declared as tokens, so every chip, band and meter in the
 * product renders the same status the same way.
 *
 * `ink-3` never carries meaning: it fails AA on the board and is reserved for
 * rules and disabled glyph strokes. Secondary text stops at `ink-2`.
 */
export const TONE_TEXT: Record<StatusTone, string> = {
  seal: 'text-seal',
  stamp: 'text-stamp',
  caution: 'text-caution',
  held: 'text-held',
  quiet: 'text-ink-2',
};

export const TONE_BORDER: Record<StatusTone, string> = {
  seal: 'border-seal',
  stamp: 'border-stamp',
  caution: 'border-caution',
  held: 'border-held',
  quiet: 'border-rule-strong',
};

export const TONE_WASH: Record<StatusTone, string> = {
  seal: 'bg-seal-weak',
  stamp: 'bg-stamp-weak',
  caution: 'bg-caution-weak',
  held: 'bg-held-weak',
  quiet: 'bg-board-sunk',
};

export const TONE_FILL: Record<StatusTone, string> = {
  seal: 'bg-seal',
  stamp: 'bg-stamp',
  caution: 'bg-caution',
  held: 'bg-held',
  quiet: 'bg-ink-2',
};
