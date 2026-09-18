/** Display formatting. Everything degrades to an explicit em dash, never "undefined". */

export const EMPTY_VALUE = '—';

export function formatText(value: string | null | undefined): string {
  return value === null || value === undefined || value === '' ? EMPTY_VALUE : value;
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return EMPTY_VALUE;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return EMPTY_VALUE;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toISOString().slice(0, 10);
}

export function formatAmount(amount: number | null | undefined, currency: string | null): string {
  if (amount === null || amount === undefined) return EMPTY_VALUE;
  const fixed = amount.toFixed(2);
  return currency ? `${fixed} ${currency}` : fixed;
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return EMPTY_VALUE;
  return new Intl.NumberFormat('en-GB').format(value);
}

export function formatRisk(value: number | null | undefined): string {
  if (value === null || value === undefined) return EMPTY_VALUE;
  return value <= 1 ? value.toFixed(2) : String(Math.round(value));
}

export function formatBoolean(value: boolean | null | undefined): string {
  if (value === null || value === undefined) return EMPTY_VALUE;
  return value ? 'Yes' : 'No';
}
