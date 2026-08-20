import { resolve } from "node:path";

import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";
import checker from "vite-plugin-checker";

const rootDir = __dirname;

export default defineConfig({
  plugins: [
    vue(),
    checker({ vueTsc: true }),
  ],
  resolve: {
    alias: {
      "@contracts": resolve(rootDir, "../../contracts"),
    },
  },
  server: {
    host: true,
    port: 80,
    strictPort: true,
    allowedHosts: true,
    // HMR 固定使用 wss 以避免 HTTPS 頁面的 mixed content。不設
    // clientPort，讓 Vite 從瀏覽器實際載入的 origin 推導 443 或 8787。
    hmr: {
      protocol: "wss",
      path: "/@vite/hmr",
    },
    proxy: {
      "/ws": {
        target: "http://localhost:8200",
        ws: true,
      },
      "/api": {
        target: "http://localhost:8200",
      },
      "/v1": {
        target: "http://localhost:8200",
      },
      "/tts": {
        target: "http://localhost:8200",
      },
    },
  },
  build: {
    outDir: "dist",
    assetsInlineLimit: 0, // Don't inline WASM or large assets
    rollupOptions: {
      input: resolve(rootDir, "index.html"),
    },
  },
});
