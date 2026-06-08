# syntax=docker/dockerfile:1
# ─────────────────────────────────────────────────────────────
# Production multi-stage build for the admin frontend.
#   builder → compiles the Vite/React app into static assets
#   runner  → minimal nginx image serving those assets only
# Runs as a non-root user; never writes to host bind mounts.
# For local development with hot-reload, see Dockerfile.dev.
#
# IMPORTANT: build context is the REPO ROOT, not frontend/admin,
# because the build resolves "@contracts" → ../../contracts.
#   docker build -f frontend/admin/Dockerfile -t openvman-admin:prod .
# ─────────────────────────────────────────────────────────────

# ---- builder ------------------------------------------------
FROM node:20-alpine AS builder

WORKDIR /app

# Install dependencies first (better layer caching)
COPY frontend/admin/package.json frontend/admin/pnpm-lock.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile

# Shared contracts live outside frontend/admin; the Vite/TS alias
# "@contracts" resolves to ../../contracts, so they must sit one
# level up from the app dir inside the build stage.
COPY contracts /contracts

COPY frontend/admin/ ./
RUN pnpm build

# ---- runner -------------------------------------------------
FROM nginx:1.27-alpine AS runner

ENV TZ=Asia/Taipei
RUN apk add --no-cache tzdata

# Production nginx config: serve admin static files + SPA fallback.
COPY frontend/admin/nginx/production.conf /etc/nginx/conf.d/default.conf

# Copy only the built assets from the builder stage.
COPY --from=builder /app/dist /usr/share/nginx/html/admin

# nginx:alpine already defines an unprivileged "nginx" user.
# The stock image entrypoint drops worker processes to that user;
# the master needs root only to bind :80. No host writes occur here.

EXPOSE 80

# Use the stock nginx entrypoint/CMD (daemon off).
