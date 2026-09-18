import { Suspense } from 'react';

import { Division, DivisionIntro } from '@/components/page';
import { LoadingRule } from '@/components/states';
import { SearchConsole } from '@/features/search/search-console';

export const metadata = { title: 'Search' };

export default function SearchPage() {
  return (
    <Division>
      <DivisionIntro
        title="Search"
        lede="One query, every permitted source. Each result opens at the exact page, frame, segment or row it came from, and every score can be taken apart."
      />
      <Suspense fallback={<LoadingRule label="Preparing search" />}>
        <SearchConsole />
      </Suspense>
    </Division>
  );
}
