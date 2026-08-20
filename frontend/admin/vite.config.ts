import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// 與 frontend/app/vite.config.ts 一致：預設為 native nginx 終止 TLS 的
// 標準埠，直連 Docker nginx 開發時可用 PUBLIC_HTTPS_PORT 覆寫。
const publicPort = Number(process.env.PUBLIC_HTTPS_PORT ?? 443);

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
    // HMR is reached through the nginx HTTPS edge proxy, so the client must
    // use wss on the native nginx HTTPS port (443) — not ws on the internal vite
    // port — or the browser blocks it as mixed content on an HTTPS origin.
    // nginx's /admin/ location proxies the ws upgrade through to vite.
    hmr: {
      protocol: "wss",
      clientPort: publicPort,
    },
  },
});
