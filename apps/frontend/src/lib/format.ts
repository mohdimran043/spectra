const SECONDS_PER_HOUR = 3600;
const SECONDS_PER_MINUTE = 60;
const MS_PER_SECOND = 1000;
const BYTES_PER_UNIT = 1024;

const pad2 = (value: number) => String(Math.floor(value)).padStart(2, '0');

/** `3742` → `01:02:22`. Matches `spectra_schemas.provenance.format_timestamp`. */
export function formatTimecode(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '--:--:--';
  const total = Math.max(0, Math.floor(seconds));
  return [
    pad2(total / SECONDS_PER_HOUR),
    pad2((total % SECONDS_PER_HOUR) / SECONDS_PER_MINUTE),
    pad2(total % SECONDS_PER_MINUTE),
  ].join(':');
}

export function formatTimecodeRange(
  start: number | null | undefined,
  end: number | null | undefined,
): string {
  if (start === null || start === undefined) return '--:--:--';
  if (end === null || end === undefined) return formatTimecode(start);
  return `${formatTimecode(start)} – ${formatTimecode(end)}`;
}

export function formatLatency(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return '—';
  if (ms < 1) return '<1 ms';
  if (ms < MS_PER_SECOND) return `${Math.round(ms)} ms`;
  const seconds = ms / MS_PER_SECOND;
  return seconds < 10 ? `${seconds.toFixed(2)} s` : `${seconds.toFixed(1)} s`;
}

export function formatPercent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatScore(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return value.toFixed(digits);
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let unitIndex = 0;
  while (value >= BYTES_PER_UNIT && unitIndex < units.length - 1) {
    value /= BYTES_PER_UNIT;
    unitIndex += 1;
  }
  return `${value < 10 && unitIndex > 0 ? value.toFixed(1) : Math.round(value)} ${units[unitIndex]}`;
}

export function formatMegabytes(mb: number | null | undefined): string {
  if (mb === null || mb === undefined || !Number.isFinite(mb)) return '—';
  if (mb >= BYTES_PER_UNIT) return `${(mb / BYTES_PER_UNIT).toFixed(1)} GB`;
  return `${Math.round(mb)} MB`;
}

function toDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** `10:42:01` — the timeline's own format. */
export function formatClock(value: string | null | undefined): string {
  const date = toDate(value);
  if (!date) return '--:--:--';
  return [date.getHours(), date.getMinutes(), date.getSeconds()].map(pad2).join(':');
}

export function formatDate(value: string | null | undefined): string {
  const date = toDate(value);
  if (!date) return '—';
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: '2-digit' });
}

export function formatDateTime(value: string | null | undefined): string {
  const date = toDate(value);
  if (!date) return '—';
  return `${formatDate(value)} ${formatClock(value)}`;
}

const RELATIVE_STEPS: ReadonlyArray<readonly [number, Intl.RelativeTimeFormatUnit]> = [
  [60, 'second'],
  [60, 'minute'],
  [24, 'hour'],
  [7, 'day'],
  [4.348, 'week'],
  [12, 'month'],
];

export function formatRelative(value: string | null | undefined): string {
  const date = toDate(value);
  if (!date) return '—';
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
  let delta = (date.getTime() - Date.now()) / MS_PER_SECOND;
  let unit: Intl.RelativeTimeFormatUnit = 'second';
  for (const step of RELATIVE_STEPS) {
    if (Math.abs(delta) < step[0]) break;
    delta /= step[0];
    unit = step[1];
  }
  return formatter.format(Math.round(delta), unit);
}

/** Identifiers read better broken at the prefix: `evd_ab12cd34` → `evd · ab12cd34`. */
export function splitId(id: string): { prefix: string; body: string } {
  const separator = id.indexOf('_');
  if (separator <= 0) return { prefix: '', body: id };
  return { prefix: id.slice(0, separator), body: id.slice(separator + 1) };
}

export function truncate(value: string, max: number): string {
  if (value.length <= max) return value;
  return `${value.slice(0, max - 1).trimEnd()}…`;
}
