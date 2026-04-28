# syntax=docker/dockerfile:1.7

# --- Stage 1: Builder (deps prewarm for volume mount layout) ---
FROM node:20-alpine AS builder

WORKDIR /app
COPY package*.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci

# --- Stage 2: Runner (vite dev server) ---
FROM node:20-alpine AS runner

ENV TZ=Asia/Taipei
RUN apk add --no-cache tzdata

WORKDIR /app
COPY --from=builder /app/node_modules ./node_modules

EXPOSE 80

CMD ["npx", "vite", "--host", "--port", "80"]
