# syntax=docker/dockerfile:1
# Admin frontend image. Build context is the repo root because Vite resolves
# "@contracts" to ../../contracts.

FROM node:20-alpine AS deps

WORKDIR /app

COPY frontend/admin/package.json frontend/admin/pnpm-lock.yaml ./
RUN corepack enable && corepack prepare pnpm@9.15.4 --activate && pnpm install --frozen-lockfile

FROM deps AS dev

ENV TZ=Asia/Taipei
# Vite runs as the node user under supervisord; keep bind/volume writes non-root.
RUN apk add --no-cache tzdata nginx openssl supervisor \
    && chown -R node:node /app

COPY frontend/admin/nginx/http.d/ /etc/nginx/http.d/
COPY frontend/admin/docker/ensure-https-cert.sh /usr/local/bin/ensure-https-cert
COPY frontend/admin/supervisord.conf /etc/supervisord.conf
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

EXPOSE 80
