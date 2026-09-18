import Link from 'next/link';

interface PaginationProps {
  basePath: string;
  page: number;
  pageCount: number;
  total: number;
}

export function Pagination({ basePath, page, pageCount, total }: PaginationProps) {
  if (total === 0) return null;
  const previousHref = `${basePath}?page=${page - 1}`;
  const nextHref = `${basePath}?page=${page + 1}`;
  return (
    <nav
      aria-label="Pagination"
      className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-3 py-2 text-xxs"
    >
      <p className="text-ink-muted">
        Page {page} of {pageCount} · {total} record{total === 1 ? '' : 's'}
      </p>
      <p className="flex gap-3">
        {page > 1 ? <Link href={previousHref}>← Previous</Link> : <span className="text-ink-faint">← Previous</span>}
        {page < pageCount ? <Link href={nextHref}>Next →</Link> : <span className="text-ink-faint">Next →</span>}
      </p>
    </nav>
  );
}
