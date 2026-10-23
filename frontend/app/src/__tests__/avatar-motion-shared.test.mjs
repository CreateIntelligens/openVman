import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

test("the tested preview and the Vman pilot use identical motion controllers", async () => {
  for (const name of ["motion-controller.js", "video-cache.js"]) {
    const shared = new URL(`../../../shared/avatar/motion/${name}`, import.meta.url);
    const preview = new URL(`../../public/experiments/avatar-motion/${name}`, import.meta.url);
    assert.equal(await readFile(preview, "utf8"), await readFile(shared, "utf8"),
      `${name} 已分歧；執行 node scripts/sync-avatar-motion.mjs 同步預覽`);
  }
});
