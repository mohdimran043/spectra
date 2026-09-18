import type { Metadata } from 'next';
import type { ReactNode } from 'react';

import { SiteFooter } from '@/components/layout/SiteFooter';
import { SiteHeader } from '@/components/layout/SiteHeader';

import './globals.css';

export const metadata: Metadata = {
  title: {
    default: 'Operations Console',
    template: '%s · Operations Console',
  },
  description:
    'Internal operations console for customers, transactions, incidents and assets.',
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="flex min-h-screen flex-col bg-white">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:bg-white focus:px-3 focus:py-2 focus:text-ink"
        >
          Skip to main content
        </a>
        <SiteHeader />
        <main id="main" className="mx-auto w-full max-w-[1200px] flex-1 px-4 py-5">
          {children}
        </main>
        <SiteFooter />
      </body>
    </html>
  );
}
