import type { Metadata, Viewport } from 'next';

import { AppShell } from '@/features/shell/app-shell';
import { THEME_STORAGE_KEY } from '@/lib/role';
import { DIRECTION_CONTRACT } from './direction-contract';
import { Providers } from './providers';
import './globals.css';

export const metadata: Metadata = {
  title: {
    default: 'SPECTRA · AI Investigation Intelligence',
    template: '%s · SPECTRA',
  },
  description:
    'Enterprise investigation console: cross-modal retrieval, claims tested against their own disproof probes, and every fact openable at its source.',
  applicationName: 'SPECTRA',
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#edebe4' },
    { media: '(prefers-color-scheme: dark)', color: '#0e1013' },
  ],
};

/**
 * The stored theme is applied before first paint. Without this the night shift
 * gets a white flash on every navigation, which on a dark ops floor is a real
 * defect rather than a cosmetic one.
 */
const THEME_BOOTSTRAP = `(function(){try{var t=localStorage.getItem('${THEME_STORAGE_KEY}');document.documentElement.setAttribute('data-theme',t==='dark'?'dark':'light');}catch(e){document.documentElement.setAttribute('data-theme','light');}})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
      </head>
      <body>
        <div hidden dangerouslySetInnerHTML={{ __html: DIRECTION_CONTRACT }} />
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
