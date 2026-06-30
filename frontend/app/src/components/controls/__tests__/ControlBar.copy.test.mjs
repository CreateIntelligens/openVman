import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../ControlBar.vue"), "utf8");

test("control bar presents one merged virtual human console title", () => {
  assert.match(source, /<h2>openVman console<\/h2>/);
  assert.doesNotMatch(source, /Reception Console/);
  assert.doesNotMatch(source, /control-bar__eyebrow/);
});
