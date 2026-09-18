import type { Metadata } from 'next';
import { Suspense } from 'react';

import { SearchConsole } from '@/features/search/search-console';

export const metadata: Metadata = {
  title: 'SPECTRA',
  description: 'Search documents, images, video, audio and records together.',
};

export default function HomePage() {
  // `SearchConsole` reads `?q=` to re-run a search from the Activity page, and
  // `useSearchParams` forces client rendering. The boundary keeps the shell
  // static so the page still prerenders.
  return (
    <Suspense fallback={null}>
      <SearchConsole />
    </Suspense>
  );
}
