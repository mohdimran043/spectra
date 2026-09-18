# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# SPECTRA mock enterprise application (Next.js, standalone output).
#
#   docker build -f docker/mock-enterprise.Dockerfile -t spectra-mock-enterprise:1.0.0 .
#
# Build context is the repository ROOT so the single root .dockerignore applies.
# Requires `output: "standalone"` in apps/mock-enterprise/next.config.*.
# Kept structurally identical to docker/frontend.Dockerfile - change both.
# ---------------------------------------------------------------------------

ARG NODE_VERSION=20

# =========================== stage: deps ===================================
FROM node:${NODE_VERSION}-alpine AS deps

WORKDIR /app

RUN apk add --no-cache libc6-compat

# One COPY, anchored on package.json: a COPY whose globs all match nothing is a
# build error, so the lockfile globs must travel with a path that always exists.
COPY package.json \
     package-lock.json* \
     npm-shrinkwrap.json* \
     pnpm-lock.yaml* \
     yarn.lock* \
     ./

RUN corepack enable \
    && if   [ -f pnpm-lock.yaml ];      then pnpm install --frozen-lockfile; \
       elif [ -f yarn.lock ];           then yarn install --frozen-lockfile; \
       elif [ -f package-lock.json ];   then npm ci; \
       elif [ -f npm-shrinkwrap.json ]; then npm ci; \
       else npm install; fi

# ========================== stage: builder =================================
FROM node:${NODE_VERSION}-alpine AS builder

WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1 \
    NODE_ENV=production

COPY --from=deps /app/node_modules ./node_modules
COPY . ./

RUN corepack enable \
    && if   [ -f pnpm-lock.yaml ]; then pnpm run build; \
       elif [ -f yarn.lock ];      then yarn build; \
       else npm run build; fi

# Not every Next.js app has a public/ directory; create it so the runtime stage
# can copy it unconditionally.
RUN mkdir -p public

# ========================== stage: runtime =================================
FROM node:${NODE_VERSION}-alpine AS runtime

ARG APP_PORT=3001
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=${APP_PORT} \
    HOSTNAME=0.0.0.0

# `node` (uid 1000) ships with the image; no secrets, no build tools here.
# The database URL (read-only role) is injected at run time, never at build time.
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static
COPY --from=builder --chown=node:node /app/public ./public

USER node

EXPOSE 3001

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=5 \
    CMD node -e "fetch('http://127.0.0.1:'+(process.env.PORT||3001)+'/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

# server.js sits at the root of the standalone output for a single-app context,
# and one level down when Next detects a workspace root.  Handle both.
CMD ["sh", "-c", "if [ -f server.js ]; then exec node server.js; else exec node \"$(find . -maxdepth 4 -name server.js -not -path './node_modules/*' | head -n 1)\"; fi"]
