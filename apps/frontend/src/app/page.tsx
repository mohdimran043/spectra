import type { Metadata } from 'next';

import { SearchConsole } from '@/features/search/search-console';

export const metadata: Metadata = {
  title: 'SPECTRA',
  description: 'Search documents, images, video, audio and records together.',
};

export default function HomePage() {
  return <SearchConsole />;
}
