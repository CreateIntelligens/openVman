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
  },
});
