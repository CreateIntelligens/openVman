import { resolve } from "node:path";

import { defineConfig } from "vite";

export default defineConfig(({ mode }) => ({
  resolve: {
    alias: mode === "test" ? [{
      find: /.*shared\/avatar-engine\/index\.mjs$/,
      replacement: resolve(__dirname, "tests/fake-engine.ts"),
    }] : [],
  },
  build: {
    lib: {
      entry: resolve(__dirname, "src/main.ts"),
      formats: ["iife"],
      name: "OpenVmanAvatarBundle",
      fileName: () => "openvman-avatar-sdk.js",
    },
    outDir: mode === "test" ? "dist/test" : "dist",
    emptyOutDir: true,
  },
}));
