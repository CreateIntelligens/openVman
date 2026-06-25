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
    // HMR is reached through the nginx HTTPS edge proxy, so the client must
    // use wss on the public HTTPS port (8787) — not ws on the internal vite
    // port — or the browser blocks it as mixed content on an HTTPS origin.
    // nginx's /admin/ location proxies the ws upgrade through to vite.
    hmr: {
      protocol: "wss",
      clientPort: 8787,
    },
  },
});
