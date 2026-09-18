import type { ReactNode } from 'react';

import { cn } from './cn';

/**
 * Ply is the only rank in this product: board (the page ground) → leaf (a panel
 * of the record) → overlay (the drawer). Nothing nests a leaf inside a leaf, and
 * nothing else is allowed to elevate.
 */
export function Leaf({
  children,
  className,
  as: Tag = 'section',
  flush = false,
}: {
  children: ReactNode;
  className?: string;
  as?: 'section' | 'div' | 'article' | 'aside';
  flush?: boolean;
}) {
  return (
    <Tag
      className={cn(
        'border border-rule bg-leaf shadow-leaf',
        flush ? '' : 'rounded-sm',
        className,
      )}
    >
      {children}
    </Tag>
  );
}

/**
 * The leaf's head band: a division name at micro caps, an optional count, and
 * whatever control belongs to that division. It is the only place a section
 * title appears — headings never float free on the board.
 */
export function LeafHead({
  title,
  count,
  hint,
  actions,
  id,
  className,
}: {
  title: string;
  count?: number | string;
  hint?: string;
  actions?: ReactNode;
  id?: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        'flex min-h-[2.125rem] flex-wrap items-center gap-x-3 gap-y-1 border-b border-rule px-3 py-1.5',
        className,
      )}
    >
      <h2
        id={id}
        className="text-micro font-semibold uppercase tracking-[0.1em] text-ink-1"
      >
        {title}
      </h2>
      {count !== undefined && (
        <span className="tabular font-mono text-micro text-ink-2">{count}</span>
      )}
      {hint && <span className="text-micro text-ink-2">{hint}</span>}
      {actions && <div className="ml-auto flex items-center gap-1.5">{actions}</div>}
    </div>
  );
}

export function LeafBody({
  children,
  className,
  padded = true,
}: {
  children: ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return <div className={cn(padded && 'p-3', className)}>{children}</div>;
}

/** A hairline division inside a leaf. The record is ruled, not boxed. */
export function Rule({ className }: { className?: string }) {
  return <hr className={cn('border-0 border-t border-rule', className)} />;
}

/** A labelled measurement pair — the record's smallest unit of fact. */
export function Reading({
  label,
  value,
  mono = true,
  tone,
  className,
}: {
  label: string;
  value: ReactNode;
  mono?: boolean;
  tone?: string;
  className?: string;
}) {
  return (
    <div className={cn('flex flex-col gap-0.5', className)}>
      <span className="text-micro uppercase tracking-[0.08em] text-ink-2">{label}</span>
      <span
        className={cn(
          'text-mark text-ink',
          mono && 'font-mono tabular',
          tone,
        )}
      >
        {value}
      </span>
    </div>
  );
}
