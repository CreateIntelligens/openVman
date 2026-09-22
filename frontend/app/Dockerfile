# syntax=docker/dockerfile:1.7

FROM node:20-alpine AS builder

WORKDIR /app
COPY frontend/app/package.json frontend/app/pnpm-lock.yaml ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    corepack enable \
    && corepack prepare pnpm@9.15.4 --activate \
    && pnpm install --frozen-lockfile

# 在 builder 裡直接 build。@shared 與 @contracts 是 ../ 相對路徑的 alias，所以
# 要放在 /app 的同層，跟 dev server 的佈局一致。
COPY contracts /contracts
COPY frontend/shared /shared
COPY frontend/app/ ./
RUN corepack pnpm build

# 正式環境只送靜態檔。之前這一層跑的是 pnpm dev——每個使用者打開頁面都在讓
# Vite 現場轉譯 TypeScript，還掛著 HMR client 與 esbuild 常駐程序。開發時的
# 熱重載由 docker-compose.dev.yml 覆寫 command 提供，不在正式 image 裡。
FROM nginx:1.27-alpine AS runner

ENV TZ=Asia/Taipei
RUN apk add --no-cache tzdata

COPY frontend/app/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80
