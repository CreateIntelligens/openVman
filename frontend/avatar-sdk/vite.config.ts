import { resolve } from "node:path";

import { defineConfig } from "vite";

export default defineConfig({
  build: {
    lib: {
      entry: resolve(__dirname, "src/main.ts"),
      formats: ["iife"],
      name: "OpenVmanAvatarBundle",
      fileName: () => "openvman-avatar-sdk.js",
    },
    outDir: "dist",
    emptyOutDir: true,
  },
});
