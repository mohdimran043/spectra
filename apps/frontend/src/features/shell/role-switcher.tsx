'use client';

import * as DropdownMenu from '@radix-ui/react-dropdown-menu';

import { cn } from '@/components/cn';
import { IconChevronDown } from '@/components/icons';
import { ROLE_SUMMARY, type Role } from '@/lib/role';
import { useSession } from './session-context';

const ROLES: readonly Role[] = ['admin', 'analyst', 'viewer'];

/**
 * The role switcher sets `X-Spectra-Role` on every subsequent request, so it
 * changes what the API returns rather than what this app chooses to draw. The
 * menu says so, because a permission control that looks decorative gets used
 * carelessly.
 */
export function RoleSwitcher() {
  const { role, setRole, hydrated } = useSession();

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger
        className={cn(
          'inline-flex items-center gap-1.5 rounded-sm border border-rule-strong bg-board-sunk px-2 py-1',
          'text-micro font-semibold uppercase tracking-[0.08em] text-ink-1 hover:border-ink-3 hover:text-ink',
        )}
        aria-label={`Acting as ${role}. Change role.`}
      >
        <span className="text-ink-2">Role</span>
        <span className="text-ink">{hydrated ? role : '—'}</span>
        <IconChevronDown size={11} />
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={6}
          className="z-50 w-[19rem] border border-rule-strong bg-overlay p-1 shadow-overlay animate-leaf-in"
        >
          <p className="px-2 py-1.5 text-micro text-ink-2">
            Sent as the <span className="font-mono">X-Spectra-Role</span> header. The API filters
            sources and capabilities against it.
          </p>
          {ROLES.map((candidate) => (
            <DropdownMenu.Item
              key={candidate}
              onSelect={() => setRole(candidate)}
              className={cn(
                'flex cursor-pointer flex-col gap-0.5 rounded-sm px-2 py-1.5 outline-none',
                'data-[highlighted]:bg-board-sunk',
                candidate === role && 'bg-held-weak',
              )}
            >
              <span className="flex items-center gap-2 text-mark font-semibold text-ink">
                {candidate}
                {candidate === role && (
                  <span className="text-micro font-normal uppercase tracking-[0.08em] text-held">
                    current
                  </span>
                )}
              </span>
              <span className="text-micro text-ink-2">{ROLE_SUMMARY[candidate]}</span>
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
