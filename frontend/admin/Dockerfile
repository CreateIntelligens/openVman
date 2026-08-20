# syntax=docker/dockerfile:1
# Admin frontend image. Build context is the repo root because Vite resolves
# "@contracts" to ../../contracts.

FROM node:20-alpine AS deps

WORKDIR /app

COPY frontend/admin/package.json frontend/admin/pnpm-lock.yaml ./
RUN corepack enable && corepack prepare pnpm@9.15.4 --activate && pnpm install --frozen-lockfile

FROM node:20-alpine AS avatar-sdk-builder

WORKDIR /sdk

COPY frontend/avatar-sdk/package.json frontend/avatar-sdk/pnpm-lock.yaml ./
RUN corepack enable \
    && corepack prepare pnpm@10.33.0 --activate \
    && pnpm install --frozen-lockfile

COPY frontend/avatar-sdk/src ./src
COPY frontend/avatar-sdk/tests ./tests
COPY frontend/avatar-sdk/tsconfig.json frontend/avatar-sdk/vite.config.ts ./
RUN pnpm test

FROM deps AS dev

ENV TZ=Asia/Taipei
# Vite runs as the node user under supervisord; keep bind/volume writes non-root.
RUN apk add --no-cache tzdata nginx openssl supervisor \
    && chown node:node /app /app/node_modules

COPY frontend/admin/nginx/http.d/ /etc/nginx/http.d/
COPY frontend/admin/docker/ensure-https-cert.sh /usr/local/bin/ensure-https-cert
COPY frontend/admin/supervisord.conf /etc/supervisord.conf
COPY --from=avatar-sdk-builder /sdk/dist/openvman-avatar-sdk.js /usr/share/nginx/html/openvman-avatar-sdk.js
RUN chmod +x /usr/local/bin/ensure-https-cert

EXPOSE 80 443 5173

CMD ["supervisord", "-c", "/etc/supervisord.conf"]

FROM deps AS builder

COPY contracts /contracts

COPY frontend/admin/ ./
RUN pnpm build

FROM nginx:1.27-alpine AS runner

ENV TZ=Asia/Taipei
RUN apk add --no-cache tzdata

COPY frontend/admin/nginx/production.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html/admin
COPY --from=avatar-sdk-builder /sdk/dist/openvman-avatar-sdk.js /usr/share/nginx/html/openvman-avatar-sdk.js

EXPOSE 80
