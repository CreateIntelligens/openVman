import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  base: "/admin/",
  plugins: [react()],
  resolve: {
    alias: {
      "@contracts": path.resolve(__dirname, "../../contracts"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    allowedHosts: true,
    // HMR 固定使用 wss 以避免 HTTPS 頁面的 mixed content。不設
    // clientPort，讓 Vite 從瀏覽器實際載入的 origin 推導 443 或 8787。
    // nginx 的 /admin/ location 會將 WebSocket upgrade 代理到 Vite。
    hmr: {
      protocol: "wss",
    },
  },
});
