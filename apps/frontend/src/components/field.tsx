'use client';

import { forwardRef, useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react';

import { cn } from './cn';

const CONTROL_BASE =
  'w-full rounded-sm border border-rule-strong bg-leaf px-2 text-body text-ink placeholder:text-ink-2 ' +
  'transition-colors duration-100 ease-step hover:border-ink-3 disabled:cursor-not-allowed disabled:bg-board-sunk disabled:text-ink-2';

export function FieldLabel({
  htmlFor,
  children,
  hint,
  className,
}: {
  htmlFor: string;
  children: ReactNode;
  hint?: string;
  className?: string;
}) {
  return (
    <label
      htmlFor={htmlFor}
      className={cn('flex items-baseline gap-2 text-micro uppercase tracking-[0.08em] text-ink-1', className)}
    >
      <span className="font-semibold">{children}</span>
      {hint && <span className="normal-case tracking-normal text-ink-2">{hint}</span>}
    </label>
  );
}

export interface TextFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  readonly label: string;
  readonly hint?: string;
  readonly error?: string;
  readonly mono?: boolean;
}

export const TextField = forwardRef<HTMLInputElement, TextFieldProps>(function TextField(
  { label, hint, error, mono, className, id, ...rest },
  ref,
) {
  const generatedId = useId();
  const fieldId = id ?? generatedId;
  const errorId = `${fieldId}-error`;
  return (
    <div className="flex flex-col gap-1">
      <FieldLabel htmlFor={fieldId} hint={hint}>
        {label}
      </FieldLabel>
      <input
        ref={ref}
        id={fieldId}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
        className={cn(CONTROL_BASE, 'h-7', mono && 'font-mono tabular', error && 'border-stamp', className)}
        {...rest}
      />
      {error && (
        <p id={errorId} className="text-micro text-stamp">
          {error}
        </p>
      )}
    </div>
  );
});

export interface SelectFieldProps extends SelectHTMLAttributes<HTMLSelectElement> {
  readonly label: string;
  readonly hint?: string;
}

export const SelectField = forwardRef<HTMLSelectElement, SelectFieldProps>(function SelectField(
  { label, hint, className, id, children, ...rest },
  ref,
) {
  const generatedId = useId();
  const fieldId = id ?? generatedId;
  return (
    <div className="flex flex-col gap-1">
      <FieldLabel htmlFor={fieldId} hint={hint}>
        {label}
      </FieldLabel>
      <select ref={ref} id={fieldId} className={cn(CONTROL_BASE, 'h-7', className)} {...rest}>
        {children}
      </select>
    </div>
  );
});

export interface TextAreaFieldProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  readonly label: string;
  readonly hint?: string;
}

export const TextAreaField = forwardRef<HTMLTextAreaElement, TextAreaFieldProps>(
  function TextAreaField({ label, hint, className, id, ...rest }, ref) {
    const generatedId = useId();
    const fieldId = id ?? generatedId;
    return (
      <div className="flex flex-col gap-1">
        <FieldLabel htmlFor={fieldId} hint={hint}>
          {label}
        </FieldLabel>
        <textarea
          ref={ref}
          id={fieldId}
          className={cn(CONTROL_BASE, 'resize-y py-1.5 leading-[1.4]', className)}
          {...rest}
        />
      </div>
    );
  },
);
