# syntax=docker/dockerfile:1.7

FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json pnpm-lock.yaml ./
RUN corepack enable \
    && corepack prepare pnpm@10.33.0 --activate \
    && pnpm install --frozen-lockfile

COPY src ./src
COPY tests ./tests
COPY tsconfig.json vite.config.ts ./
RUN pnpm test

FROM nginx:1.27-alpine AS runner

COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80
