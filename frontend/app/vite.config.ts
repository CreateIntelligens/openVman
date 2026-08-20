import { resolve } from "node:path";

import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";
import checker from "vite-plugin-checker";

const publicPort = Number(process.env.PUBLIC_HTTPS_PORT ?? 443);
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
    // Page is served over HTTPS via the nginx edge proxy, so HMR must use wss
    // or the browser blocks it as mixed content. clientPort is the public
    // Native nginx terminates HTTPS on the standard public port, since that is
    // the origin the browser actually loaded.
    hmr: {
      protocol: "wss",
      clientPort: publicPort,
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
