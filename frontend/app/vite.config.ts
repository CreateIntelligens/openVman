import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import checker from "vite-plugin-checker";
import { resolve } from "node:path";

const publicPort = Number(process.env.PORT ?? 8787);
const rootDir = __dirname;

export default defineConfig({
  plugins: [
    vue(),
    checker({ vueTsc: true }),
  ],
  server: {
    host: true,
    port: 80,
    strictPort: true,
    allowedHosts: true,
    // Page is served over HTTPS via the nginx edge proxy, so HMR must use wss
    // or the browser blocks it as mixed content. clientPort is the public
    // HTTPS port (8787), since that's the origin the browser actually loaded.
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
      input: {
        main: resolve(rootDir, "index.html"),
        embed: resolve(rootDir, "embed/avatar.html"),
      },
    },
  },
});
