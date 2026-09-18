#!/usr/bin/env bash
# Build and serve the SPECTRA console from its standalone output.
#
# `output: standalone` deliberately does NOT copy `.next/static` or `public`
# into `.next/standalone` - Next expects the deployment to place them, and the
# Dockerfile does. Running the standalone server straight from the repo without
# that step serves the HTML with no stylesheet and no client chunks, which looks
# like a broken design rather than a missing file. This script does the copy.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../apps/frontend" && pwd)"
PORT="${PORT:-3000}"
# NOTE: `HOSTNAME` is a bash built-in already set to the machine name, so
# `${HOSTNAME:-0.0.0.0}` silently binds Next to that host and the server
# becomes unreachable on every other interface. Use our own variable.
BIND_HOST="${BIND_HOST:-0.0.0.0}"
API_ORIGIN="${SPECTRA_API_ORIGIN:-http://127.0.0.1:8000}"

cd "$APP_DIR"

if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
  echo "building console..."
  npm run build
fi

echo "staging static assets into the standalone output..."
mkdir -p .next/standalone/.next
cp -r .next/static/. .next/standalone/.next/static/
if [[ -d public ]]; then
  mkdir -p .next/standalone/public
  cp -r public/. .next/standalone/public/
fi

echo "serving on http://${BIND_HOST}:${PORT} (API proxied to ${API_ORIGIN})"
exec env SPECTRA_API_ORIGIN="$API_ORIGIN" PORT="$PORT" HOSTNAME="$BIND_HOST" \
  node .next/standalone/server.js
