import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@contracts": path.resolve(__dirname, "../../contracts"),
    },
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
  },
});
