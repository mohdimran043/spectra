/**
 * The console talks to the SPECTRA API through its OWN origin by default.
 *
 * `NEXT_PUBLIC_API_BASE_URL` is baked into the browser bundle at build time, so
 * pointing it at `http://localhost:8000` only works when the browser runs on the
 * same host as the API. Anyone opening the console over the network - a LAN
 * address, a port forward, a container - then sees "API unreachable", because
 * `localhost` means *their* machine.
 *
 * Proxying `/api/*` from the Next server removes that whole class of problem:
 * the browser only ever needs the one port it already loaded the page from, and
 * CORS stops mattering. `SPECTRA_API_ORIGIN` (server-side, not baked) says where
 * the API actually lives; set `NEXT_PUBLIC_API_BASE_URL` to bypass the proxy for
 * a split deployment where the API is on its own public origin.
 */
const API_ORIGIN = (process.env.SPECTRA_API_ORIGIN || 'http://127.0.0.1:8000').replace(/\/$/, '');

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  reactStrictMode: true,
  poweredByHeader: false,
  eslint: { dirs: ['src'] },
  experimental: { typedRoutes: false },
  async rewrites() {
    return [{ source: '/api/:path*', destination: `${API_ORIGIN}/api/:path*` }];
  },
};

module.exports = nextConfig;
