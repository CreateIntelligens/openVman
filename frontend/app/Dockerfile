# syntax=docker/dockerfile:1.7

FROM node:20-alpine AS builder

WORKDIR /app
COPY frontend/app/package.json frontend/app/pnpm-lock.yaml ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    corepack enable \
    && corepack prepare pnpm@9.15.4 --activate \
    && pnpm install --frozen-lockfile

FROM node:20-alpine AS runner

ENV TZ=Asia/Taipei
RUN apk add --no-cache tzdata

WORKDIR /app
COPY --from=builder /app/node_modules ./node_modules
COPY contracts /contracts
COPY frontend/app/ ./

EXPOSE 80

CMD ["corepack", "pnpm", "dev", "--", "--host", "0.0.0.0", "--port", "80"]
