import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../AsrButton.vue"), "utf8");

test("microphone has distinct hover, focus, pressed, listening, and disabled states", () => {
  assert.match(source, /@media \(hover: hover\)/);
  assert.match(source, /\.asr-btn:focus-visible/);
  assert.match(source, /\.asr-btn:active:not\(:disabled\)/);
  assert.match(source, /\.asr-btn--active/);
  assert.match(source, /\.asr-btn:disabled/);
});

test("listening indicator stays inside the button instead of expanding over the composer", () => {
  assert.match(source, /class="asr-btn__status"/);
  assert.doesNotMatch(source, /asr-btn__pulse/);
  assert.doesNotMatch(source, /scale\(1\.5\)/);
});
