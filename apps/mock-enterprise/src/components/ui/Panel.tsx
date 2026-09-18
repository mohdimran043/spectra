import type { ReactNode } from 'react';

interface PanelProps {
  title: string;
  /** Optional right-hand note, e.g. a row count. */
  note?: string;
  children: ReactNode;
}

export function Panel({ title, note, children }: PanelProps) {
  return (
    <section className="panel mb-5">
      <h2 className="panel-title flex items-baseline justify-between gap-3">
        <span>{title}</span>
        {note ? <span className="font-normal normal-case text-ink-muted">{note}</span> : null}
      </h2>
      {children}
    </section>
  );
}
