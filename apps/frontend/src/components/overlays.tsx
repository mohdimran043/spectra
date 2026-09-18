'use client';

import * as DialogPrimitive from '@radix-ui/react-dialog';
import * as PopoverPrimitive from '@radix-ui/react-popover';
import * as TooltipPrimitive from '@radix-ui/react-tooltip';
import type { ReactNode } from 'react';

import { cn } from './cn';
import { IconClose } from './icons';

/**
 * Overlay is the third and final ply. Radix owns focus trapping, escape, scroll
 * locking and the returned focus; the styling here only draws the record's own
 * edge and shadow.
 */
export function Drawer({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  width = 'wide',
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
  width?: 'wide' | 'narrow';
}) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-scrim animate-scrim-in" />
        <DialogPrimitive.Content
          className={cn(
            'fixed inset-y-0 right-0 z-50 flex w-full flex-col border-l border-rule-strong bg-overlay shadow-overlay',
            'animate-overlay-in focus:outline-none',
            width === 'wide' ? 'max-w-[54rem]' : 'max-w-[34rem]',
          )}
        >
          <header className="flex items-start gap-3 border-b border-rule px-4 py-2.5">
            <div className="min-w-0 flex-1">
              <DialogPrimitive.Title className="truncate text-head font-semibold text-ink">
                {title}
              </DialogPrimitive.Title>
              <DialogPrimitive.Description
                className={cn('mt-0.5 text-mark text-ink-2', !description && 'sr-only')}
              >
                {description ?? title}
              </DialogPrimitive.Description>
            </div>
            <DialogPrimitive.Close
              className="rounded-sm border border-transparent p-1 text-ink-2 hover:border-rule-strong hover:text-ink"
              aria-label="Close"
            >
              <IconClose size={14} />
            </DialogPrimitive.Close>
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
          {footer && <footer className="border-t border-rule px-4 py-2.5">{footer}</footer>}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

export function InfoPopover({
  trigger,
  children,
  label,
  align = 'start',
  className,
}: {
  trigger: ReactNode;
  children: ReactNode;
  label: string;
  align?: 'start' | 'center' | 'end';
  className?: string;
}) {
  return (
    <PopoverPrimitive.Root>
      <PopoverPrimitive.Trigger asChild aria-label={label}>
        {trigger}
      </PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          align={align}
          sideOffset={6}
          collisionPadding={12}
          className={cn(
            'z-50 w-[19rem] border border-rule-strong bg-overlay p-3 shadow-overlay',
            'animate-leaf-in focus:outline-none',
            className,
          )}
        >
          {children}
          <PopoverPrimitive.Arrow className="fill-[var(--rule-strong)]" width={10} height={5} />
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}

export function TooltipProvider({ children }: { children: ReactNode }) {
  return (
    <TooltipPrimitive.Provider delayDuration={220} skipDelayDuration={80}>
      {children}
    </TooltipPrimitive.Provider>
  );
}

export function Tooltip({
  trigger,
  children,
  side = 'top',
}: {
  trigger: ReactNode;
  children: ReactNode;
  side?: 'top' | 'right' | 'bottom' | 'left';
}) {
  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>{trigger}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          side={side}
          sideOffset={5}
          collisionPadding={10}
          className="z-50 max-w-[22rem] border border-rule-strong bg-overlay px-2.5 py-1.5 text-mark text-ink shadow-overlay animate-leaf-in"
        >
          {children}
          <TooltipPrimitive.Arrow className="fill-[var(--rule-strong)]" width={9} height={4} />
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}
