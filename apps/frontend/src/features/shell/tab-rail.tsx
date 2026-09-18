'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { cn } from '@/components/cn';
import { WordmarkGlyph } from '@/components/wordmark';
import { NAV_DIVISIONS, NAV_GROUP_LABEL, type NavDivision } from './nav-items';

function isActive(pathname: string, href: string): boolean {
  if (href === '/') return pathname === '/';
  return pathname === href || pathname.startsWith(`${href}/`);
}

/**
 * The fore-edge tab rail. The active tab extends into the board and becomes the
 * ground, which is the one navigation metaphor this product uses: you are always
 * looking at one division of one record.
 */
export function TabRail({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const groups: NavDivision['group'][] = ['record', 'system'];

  return (
    <nav aria-label="Divisions" className="flex h-full flex-col gap-4 py-3">
      <Link
        href="/"
        onClick={onNavigate}
        className="mx-3 flex items-center gap-2 rounded-sm text-ink hover:text-focus"
      >
        <WordmarkGlyph size={20} />
        <span className="text-mark font-semibold uppercase tracking-[0.16em]">Spectra</span>
      </Link>

      {groups.map((group) => (
        <div key={group} className="flex flex-col gap-0.5">
          <span className="px-3 pb-1 text-micro uppercase tracking-[0.11em] text-ink-2">
            {NAV_GROUP_LABEL[group]}
          </span>
          <ul className="flex flex-col">
            {NAV_DIVISIONS.filter((division) => division.group === group).map((division) => {
              const active = isActive(pathname, division.href);
              const Glyph = division.icon;
              return (
                <li key={division.href}>
                  <Link
                    href={division.href}
                    onClick={onNavigate}
                    aria-current={active ? 'page' : undefined}
                    className={cn(
                      'group relative flex items-center gap-2.5 py-1.5 pl-3 pr-2 text-mark',
                      'transition-colors duration-100 ease-step',
                      active
                        ? 'tab-extend bg-board text-ink'
                        : 'text-ink-1 hover:bg-board-sunk hover:text-ink',
                    )}
                  >
                    <Glyph size={14} className={active ? 'text-ink' : 'text-ink-2'} />
                    <span className={cn(active && 'font-semibold')}>{division.label}</span>
                    <span className="ml-auto font-mono text-micro tabular text-ink-2 opacity-0 transition-opacity group-hover:opacity-100">
                      {division.address}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}
