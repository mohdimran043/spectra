'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';

import { cn } from '@/components/cn';
import { Drawer } from '@/components/overlays';
import { EmptyState } from '@/components/states';
import { NAV_DIVISIONS } from './nav-items';

const INVESTIGATION_ID_PATTERN = /^inv_[A-Za-z0-9]+$/;

interface PaletteEntry {
  readonly href: string;
  readonly label: string;
  readonly detail: string;
}

/**
 * DIRECTLY ADDRESSABLE: every division has a keyed address and every
 * investigation id is a destination. Typing `inv_…` goes straight to that
 * record, which is how an operator arrives from a ticket or a colleague.
 */
export function CommandPalette({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const router = useRouter();
  const [query, setQuery] = useState('');

  useEffect(() => {
    if (!open) setQuery('');
  }, [open]);

  const entries = useMemo<PaletteEntry[]>(() => {
    const trimmed = query.trim();
    const base: PaletteEntry[] = NAV_DIVISIONS.map((division) => ({
      href: division.href,
      label: division.label,
      detail: `Address ${division.address}`,
    }));

    if (INVESTIGATION_ID_PATTERN.test(trimmed)) {
      base.unshift(
        {
          href: `/investigations/${trimmed}`,
          label: `Open investigation ${trimmed}`,
          detail: 'Workspace',
        },
        {
          href: `/investigations/${trimmed}/trace`,
          label: `Agent trace for ${trimmed}`,
          detail: 'Trace',
        },
        {
          href: `/investigations/${trimmed}/autopsy`,
          label: `Search autopsy for ${trimmed}`,
          detail: 'Autopsy',
        },
      );
    }

    if (!trimmed) return base;
    const needle = trimmed.toLowerCase();
    return base.filter(
      (entry) =>
        entry.label.toLowerCase().includes(needle) ||
        entry.detail.toLowerCase().includes(needle) ||
        entry.href.includes(needle),
    );
  }, [query]);

  const go = (href: string) => {
    onOpenChange(false);
    router.push(href);
  };

  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      title="Jump to"
      description="Type a division name, a keyed address, or an investigation id."
      width="narrow"
    >
      <div className="border-b border-rule p-3">
        {/* eslint-disable-next-line jsx-a11y/no-autofocus */}
        <input
          autoFocus
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && entries[0]) go(entries[0].href);
          }}
          placeholder="Search · inv_… · 200"
          aria-label="Jump to division or investigation"
          className="h-8 w-full rounded-sm border border-rule-strong bg-leaf px-2 text-body text-ink placeholder:text-ink-2"
        />
      </div>
      {entries.length === 0 ? (
        <EmptyState
          title="No destination matches"
          body="Divisions are matched by name or keyed address. An investigation id looks like inv_ followed by 16 hex characters."
        />
      ) : (
        <ul className="flex flex-col">
          {entries.map((entry, index) => (
            <li key={entry.href}>
              <button
                type="button"
                onClick={() => go(entry.href)}
                className={cn(
                  'flex w-full items-baseline gap-3 border-b border-rule px-3 py-2 text-left hover:bg-board-sunk',
                  index === 0 && 'bg-held-weak',
                )}
              >
                <span className="text-body text-ink">{entry.label}</span>
                <span className="ml-auto font-mono text-micro tabular text-ink-2">
                  {entry.detail}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Drawer>
  );
}
