'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { cn } from '@/components/cn';
import { StatusChip } from '@/components/chip';
import { IconSearch } from '@/components/icons';
import { API_BASE_LABEL } from '@/lib/env';
import { NAV_DIVISIONS } from './nav-items';
import { RoleSwitcher } from './role-switcher';
import { ThemeToggle } from './theme-toggle';
import { useHealth } from './use-health';

function divisionLabel(pathname: string): string {
  if (pathname.startsWith('/investigations/')) {
    if (pathname.endsWith('/trace')) return 'Investigation · Agent trace';
    if (pathname.endsWith('/autopsy')) return 'Investigation · Search autopsy';
    return 'Investigation';
  }
  const match = NAV_DIVISIONS.find(
    (division) => division.href !== '/' && pathname.startsWith(division.href),
  );
  return match?.label ?? 'Record';
}

/**
 * The record line. It is always present and always says the same three things:
 * where you are, whether the machine behind it is answering, and in whose seat
 * you are sitting.
 */
export function StatusHeader({ onOpenPalette }: { onOpenPalette: () => void }) {
  const pathname = usePathname();
  const health = useHealth();

  const apiState = health.isError
    ? { tone: 'stamp' as const, label: 'API unreachable' }
    : health.isPending
      ? { tone: 'quiet' as const, label: 'Checking API' }
      : health.data?.degraded || health.data?.status !== 'ok'
        ? { tone: 'caution' as const, label: `API ${health.data?.status ?? 'degraded'}` }
        : { tone: 'seal' as const, label: 'API ok' };

  return (
    <header className="flex h-header items-center gap-3 border-b border-rule bg-leaf px-3">
      <h1 className="truncate text-mark font-semibold uppercase tracking-[0.1em] text-ink">
        {divisionLabel(pathname)}
      </h1>

      <button
        type="button"
        onClick={onOpenPalette}
        className={cn(
          'ml-2 hidden items-center gap-2 rounded-sm border border-rule-strong bg-board-sunk px-2 py-1',
          'text-micro text-ink-2 hover:border-ink-3 hover:text-ink md:inline-flex',
        )}
      >
        <IconSearch size={12} />
        <span>Jump to division or investigation</span>
        <kbd className="ml-2 rounded-sm border border-rule px-1 font-mono text-micro tabular text-ink-2">
          Ctrl K
        </kbd>
      </button>

      <div className="ml-auto flex items-center gap-2">
        <Link
          href="/settings"
          className="rounded-sm"
          title={`SPECTRA API · ${API_BASE_LABEL}`}
        >
          <StatusChip tone={apiState.tone}>{apiState.label}</StatusChip>
        </Link>
        <RoleSwitcher />
        <ThemeToggle />
      </div>
    </header>
  );
}
