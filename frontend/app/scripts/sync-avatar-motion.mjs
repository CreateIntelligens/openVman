import { readFile, writeFile } from "node:fs/promises";

for (const name of ["motion-controller.js", "video-cache.js"]) {
  const canonical = new URL(`../../shared/avatar/motion/${name}`, import.meta.url);
  const preview = new URL(`../public/experiments/avatar-motion/${name}`, import.meta.url);
  const content = await readFile(canonical, "utf8");
  if (process.argv.includes("--check")) {
    if (await readFile(preview, "utf8") !== content) {
      throw new Error(`${name} 預覽副本過期，請執行 node scripts/sync-avatar-motion.mjs`);
    }
  } else await writeFile(preview, content);
}
