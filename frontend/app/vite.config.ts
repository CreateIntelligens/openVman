import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

const publicPort = Number(process.env.PORT ?? 8787);

export default defineConfig({
  plugins: [vue()],
  server: {
    host: true,
    port: 80,
    strictPort: true,
    allowedHosts: true,
    hmr: {
      protocol: "ws",
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
    },
  },
  build: {
    outDir: "dist",
    assetsInlineLimit: 0, // Don't inline WASM or large assets
  },
});
