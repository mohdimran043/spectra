'use client';

import { useCallback, useEffect, useState, type ReactNode } from 'react';

import { Button } from '@/components/button';
import { cn } from '@/components/cn';
import { IconClose, IconFilter } from '@/components/icons';
import { CommandPalette } from './command-palette';
import { StatusHeader } from './status-header';
import { TabRail } from './tab-rail';

/**
 * The console frame: a fore-edge tab rail, a record line, and the division
 * itself. Below `lg` the rail collapses behind a control rather than reflowing
 * into a drawer of cards, because a rail that wraps stops being a rail.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const [railOpen, setRailOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);

  const openPalette = useCallback(() => setPaletteOpen(true), []);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  return (
    <div className="flex min-h-screen w-full">
      <a
        href="#division"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[60] focus:rounded-sm focus:border focus:border-ink focus:bg-leaf focus:px-3 focus:py-1.5 focus:text-mark"
      >
        Skip to content
      </a>

      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-40 w-rail shrink-0 overflow-y-auto border-r border-rule bg-leaf',
          'lg:sticky lg:top-0 lg:block lg:h-screen',
          railOpen ? 'block shadow-overlay' : 'hidden lg:block',
        )}
      >
        <TabRail onNavigate={() => setRailOpen(false)} />
      </aside>

      {railOpen && (
        <button
          type="button"
          aria-label="Close divisions"
          onClick={() => setRailOpen(false)}
          className="fixed inset-0 z-30 bg-scrim lg:hidden"
        />
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="sticky top-0 z-30 flex items-stretch bg-leaf lg:block">
          <Button
            variant="quiet"
            size="md"
            aria-expanded={railOpen}
            aria-label={railOpen ? 'Close divisions' : 'Open divisions'}
            onClick={() => setRailOpen((open) => !open)}
            className="h-header shrink-0 rounded-none border-b border-r border-rule px-2.5 lg:hidden"
          >
            {railOpen ? <IconClose size={15} /> : <IconFilter size={15} />}
          </Button>
          <div className="min-w-0 flex-1">
            <StatusHeader onOpenPalette={openPalette} />
          </div>
        </div>

        <main id="division" className="min-w-0 flex-1 bg-board">
          {children}
        </main>
      </div>

      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
    </div>
  );
}
