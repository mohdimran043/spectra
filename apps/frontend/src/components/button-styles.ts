import { cn } from './cn';

/**
 * Button styling lives in a plain module, not the client component, so a server
 * component can render a link that looks like a control without pulling a client
 * reference it cannot call.
 */
export type ButtonVariant = 'primary' | 'secondary' | 'quiet' | 'danger';
export type ButtonSize = 'sm' | 'md' | 'lg';

export const BUTTON_VARIANT: Record<ButtonVariant, string> = {
  primary:
    'border-ink bg-ink text-ink-inverse hover:bg-ink-1 hover:border-ink-1 active:bg-ink disabled:bg-ink-3 disabled:border-ink-3',
  secondary:
    'border-rule-strong bg-leaf text-ink hover:bg-board-sunk active:bg-board disabled:text-ink-3',
  quiet:
    'border-transparent bg-transparent text-ink-1 hover:bg-board-sunk hover:text-ink active:bg-board disabled:text-ink-3',
  danger:
    'border-stamp bg-stamp-weak text-stamp hover:bg-stamp hover:text-ink-inverse disabled:opacity-50',
};

export const BUTTON_SIZE: Record<ButtonSize, string> = {
  sm: 'h-6 px-2 text-micro gap-1.5',
  md: 'h-7 px-2.5 text-mark gap-1.5',
  lg: 'h-9 px-4 text-body gap-2',
};

const BUTTON_BASE =
  'inline-flex items-center justify-center rounded-sm border font-medium transition-colors duration-100 ease-step';

export function buttonClasses(
  variant: ButtonVariant = 'secondary',
  size: ButtonSize = 'md',
  className?: string,
): string {
  return cn(BUTTON_BASE, BUTTON_VARIANT[variant], BUTTON_SIZE[size], className);
}

/** The same struck control, rendered as a link. Never nest a button in an anchor. */
export const linkButtonClasses = buttonClasses;
