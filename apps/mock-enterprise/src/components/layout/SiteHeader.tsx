import Link from 'next/link';

const NAV_ITEMS = [
  { href: '/', label: 'Overview' },
  { href: '/customers', label: 'Customers' },
  { href: '/transactions', label: 'Transactions' },
  { href: '/incidents', label: 'Incidents' },
  { href: '/assets', label: 'Assets' },
] as const;

export function SiteHeader() {
  return (
    <header className="border-b border-line bg-chrome text-white">
      <div className="mx-auto flex w-full max-w-[1200px] flex-wrap items-baseline justify-between gap-2 px-4 py-2">
        <Link href="/" className="text-sm font-bold uppercase tracking-wide text-white no-underline">
          Operations Console
        </Link>
        <p className="text-xxs uppercase tracking-wide text-gray-300">
          Internal use only · read-only view
        </p>
      </div>
      <nav aria-label="Primary" className="mx-auto w-full max-w-[1200px] px-4">
        <ul className="flex flex-wrap gap-0">
          {NAV_ITEMS.map((item) => (
            <li key={item.href}>
              <Link
                href={item.href}
                className="inline-block border-b-2 border-transparent px-3 py-2 text-xs font-semibold uppercase tracking-wide text-gray-200 no-underline hover:border-white hover:text-white"
              >
                {item.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
    </header>
  );
}
