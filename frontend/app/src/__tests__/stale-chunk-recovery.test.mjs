import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const appRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const main = readFileSync(resolve(appRoot, "src/main.ts"), "utf8");

test("the avatar app installs stale chunk recovery before mounting", () => {
  const install = main.indexOf("installStaleChunkRecovery()\n");
  assert.notEqual(install, -1);
  assert.ok(install < main.indexOf("createApp(Root)"));
});
