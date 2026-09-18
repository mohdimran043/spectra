'use client';

import { cn } from '@/components/cn';
import { IconTheme } from '@/components/icons';
import type { ThemePreference } from '@/lib/role';
import { useSession } from './session-context';

const ORDER: readonly ThemePreference[] = ['system', 'light', 'dark'];

const NEXT_LABEL: Record<ThemePreference, string> = {
  system: 'Follow system theme. Switch to light.',
  light: 'Light theme. Switch to dark.',
  dark: 'Dark theme. Follow system.',
};

/**
 * Light is the day desk, dark is the night shift. Neither is a default, so the
 * control offers all three states including "follow the machine".
 */
export function ThemeToggle() {
  const { theme, setTheme, hydrated } = useSession();
  const index = ORDER.indexOf(theme);
  const next = ORDER[(index + 1) % ORDER.length] ?? 'system';

  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      aria-label={NEXT_LABEL[theme]}
      title={NEXT_LABEL[theme]}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-sm border border-rule-strong bg-board-sunk px-2 py-1',
        'text-micro font-semibold uppercase tracking-[0.08em] text-ink-1 hover:border-ink-3 hover:text-ink',
      )}
    >
      <IconTheme size={12} />
      <span>{hydrated ? theme : '—'}</span>
    </button>
  );
}
