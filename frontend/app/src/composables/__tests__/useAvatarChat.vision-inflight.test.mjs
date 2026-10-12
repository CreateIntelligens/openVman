import { avatarChatSource } from "./helpers/avatarChatModule.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const source = avatarChatSource;

test("text-mode vision has an in-flight guard that drops overlapping frames", () => {
  assert.match(source, /let visionInFlight = false/);
  // guard at the top of the text vision sender
  assert.match(source, /if \(visionInFlight\) return\s*\n\s*visionInFlight = true/);
  // released in finally so a failed request never wedges the pipeline
  assert.match(source, /finally\s*\{\s*\n\s*visionInFlight = false/);
});
