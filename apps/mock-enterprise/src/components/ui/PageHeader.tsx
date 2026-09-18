import Link from 'next/link';
import type { ReactNode } from 'react';

export interface Crumb {
  label: string;
  href?: string;
}

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  crumbs?: readonly Crumb[];
  actions?: ReactNode;
}

export function PageHeader({ title, subtitle, crumbs, actions }: PageHeaderProps) {
  return (
    <div className="mb-4 border-b border-line pb-3">
      {crumbs && crumbs.length > 0 ? (
        <nav aria-label="Breadcrumb" className="mb-1">
          <ol className="flex flex-wrap items-center gap-1 text-xxs text-ink-muted">
            {crumbs.map((crumb, index) => (
              <li key={`${crumb.label}-${index}`} className="flex items-center gap-1">
                {index > 0 ? <span aria-hidden="true">/</span> : null}
                {crumb.href ? <Link href={crumb.href}>{crumb.label}</Link> : <span>{crumb.label}</span>}
              </li>
            ))}
          </ol>
        </nav>
      ) : null}
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="text-lg font-bold tracking-tight">{title}</h1>
        {actions}
      </div>
      {subtitle ? <p className="mt-1 text-ink-muted">{subtitle}</p> : null}
    </div>
  );
}
