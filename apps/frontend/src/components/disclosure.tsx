'use client';

import * as SwitchPrimitive from '@radix-ui/react-switch';
import { useId, useState, type ReactNode } from 'react';

import { cn } from './cn';
import { IconChevronDown } from './icons';

/**
 * A disclosure is a hinge, not an accordion card: the summary row stays put and
 * the leaf below it opens. Used for "View generated SQL", rejection reasons and
 * anything the operator needs on demand rather than always.
 */
export function Disclosure({
  summary,
  children,
  defaultOpen = false,
  className,
}: {
  summary: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const panelId = useId();

  return (
    <div className={cn('border-t border-rule', className)}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-1.5 px-3 py-1.5 text-left text-micro font-semibold uppercase tracking-[0.08em] text-ink-1 hover:bg-board-sunk hover:text-ink"
      >
        <IconChevronDown
          size={12}
          className={cn('transition-transform duration-150 ease-step', !open && '-rotate-90')}
        />
        {summary}
      </button>
      {open && (
        <div id={panelId} className="border-t border-rule bg-board-sunk">
          {children}
        </div>
      )}
    </div>
  );
}

/**
 * The agent toggle. Radix drives the semantics; the mark is a struck cell that
 * slides, in keeping with the rest of the record.
 */
export function Toggle({
  checked,
  onCheckedChange,
  disabled,
  label,
  id,
}: {
  checked: boolean;
  onCheckedChange: (next: boolean) => void;
  disabled?: boolean;
  label: string;
  id?: string;
}) {
  const generatedId = useId();
  return (
    <SwitchPrimitive.Root
      id={id ?? generatedId}
      checked={checked}
      onCheckedChange={onCheckedChange}
      disabled={disabled}
      aria-label={label}
      className={cn(
        'relative h-5 w-9 shrink-0 rounded-sm border transition-colors duration-100 ease-step',
        'disabled:cursor-not-allowed disabled:opacity-50',
        checked ? 'border-seal bg-seal-weak' : 'border-rule-strong bg-board-sunk',
      )}
    >
      <SwitchPrimitive.Thumb
        className={cn(
          'block h-3.5 w-3.5 translate-x-[2px] rounded-[1px] transition-transform duration-120 ease-step',
          'data-[state=checked]:translate-x-[18px]',
          checked ? 'bg-seal' : 'bg-ink-3',
        )}
      />
    </SwitchPrimitive.Root>
  );
}
