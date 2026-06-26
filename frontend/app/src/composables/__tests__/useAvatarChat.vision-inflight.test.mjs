import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../useAvatarChat.ts"), "utf8");

test("text-mode vision has an in-flight guard that drops overlapping frames", () => {
  assert.match(source, /let visionInFlight = false/);
  // guard at the top of the text vision sender
  assert.match(source, /if \(visionInFlight\) return\s*\n\s*visionInFlight = true/);
  // released in finally so a failed request never wedges the pipeline
  assert.match(source, /finally\s*\{\s*\n\s*visionInFlight = false/);
});
