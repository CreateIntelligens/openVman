import { defineConfig } from "vite";
import { resolve } from "node:path";

export default defineConfig({
  build: {
    outDir: "dist",
    emptyOutDir: true,
    lib: {
      entry: resolve(__dirname, "src/main.ts"),
      name: "VmanEmbed",
      formats: ["iife"],
      fileName: () => "vman-embed.js",
    },
    rollupOptions: {
      output: {
        inlineDynamicImports: true,
      },
    },
  },
});
