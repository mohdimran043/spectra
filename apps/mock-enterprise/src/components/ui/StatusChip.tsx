import { EMPTY_VALUE } from '@/lib/format';

/** Chip colours are AA-contrast, dark text on a tinted background. */
const TONES = {
  neutral: 'bg-gray-200 text-gray-900 border-gray-400',
  positive: 'bg-green-100 text-green-900 border-green-700',
  warning: 'bg-amber-100 text-amber-900 border-amber-700',
  negative: 'bg-red-100 text-red-900 border-red-700',
  info: 'bg-blue-100 text-blue-900 border-blue-700',
} as const;

type Tone = keyof typeof TONES;

const POSITIVE = ['settled', 'succeeded', 'success', 'completed', 'captured', 'paid', 'active', 'resolved', 'closed', 'healthy', 'ok'];
const NEGATIVE = ['failed', 'failure', 'declined', 'rejected', 'error', 'critical', 'sev1', 'p1', 'churned', 'suspended', 'decommissioned'];
const WARNING = ['pending', 'processing', 'open', 'investigating', 'monitoring', 'degraded', 'high', 'sev2', 'p2', 'at_risk', 'review'];
const INFO = ['refunded', 'reversed', 'chargeback', 'medium', 'low', 'sev3', 'sev4', 'p3', 'p4', 'mitigated', 'maintenance'];

function toneFor(value: string): Tone {
  const key = value.trim().toLowerCase().replace(/[\s-]+/g, '_');
  if (POSITIVE.includes(key)) return 'positive';
  if (NEGATIVE.includes(key)) return 'negative';
  if (WARNING.includes(key)) return 'warning';
  if (INFO.includes(key)) return 'info';
  return 'neutral';
}

interface StatusChipProps {
  value: string | null | undefined;
  /** Force a tone instead of deriving it from the value. */
  tone?: Tone;
}

export function StatusChip({ value, tone }: StatusChipProps) {
  if (!value) return <span className="text-ink-faint">{EMPTY_VALUE}</span>;
  const resolved = tone ?? toneFor(value);
  return (
    <span
      className={`inline-block whitespace-nowrap border px-1.5 py-0.5 text-xxs font-semibold uppercase tracking-wide ${TONES[resolved]}`}
    >
      {value}
    </span>
  );
}
