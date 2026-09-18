/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Required by the Docker image: emits a self-contained server bundle.
  output: 'standalone',
  // Native / CommonJS database drivers must not be bundled by the server compiler.
  experimental: {
    serverComponentsExternalPackages: ['better-sqlite3', 'pg'],
  },
  poweredByHeader: false,
};

module.exports = nextConfig;
