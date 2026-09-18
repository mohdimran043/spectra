'use client';

import { forwardRef, type ButtonHTMLAttributes } from 'react';

import { cn } from './cn';
import {
  BUTTON_SIZE,
  BUTTON_VARIANT,
  type ButtonSize,
  type ButtonVariant,
} from './button-styles';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  readonly variant?: ButtonVariant;
  readonly size?: ButtonSize;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', className, type = 'button', ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cn(
        'inline-flex items-center justify-center rounded-sm border font-medium',
        'transition-colors duration-100 ease-step',
        'disabled:cursor-not-allowed disabled:shadow-none',
        BUTTON_VARIANT[variant],
        BUTTON_SIZE[size],
        className,
      )}
      {...rest}
    />
  );
});

/**
 * A toggle that reads as a struck tab rather than a switch: selected is the
 * extended tab, unselected is a plain cell.
 */
export function SegmentButton({
  selected,
  className,
  ...rest
}: ButtonProps & { selected: boolean }) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      className={cn(
        'inline-flex h-6 items-center gap-1.5 rounded-sm border px-2 text-micro font-semibold uppercase tracking-[0.07em]',
        'transition-colors duration-100 ease-step',
        selected
          ? 'border-ink bg-ink text-ink-inverse'
          : 'border-rule-strong bg-leaf text-ink-1 hover:bg-board-sunk hover:text-ink',
        className,
      )}
      {...rest}
    />
  );
}
