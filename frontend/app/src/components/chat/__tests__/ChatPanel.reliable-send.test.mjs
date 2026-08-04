import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../ChatPanel.vue"), "utf8");

test("composer clears only after the send callback accepts the draft", () => {
  assert.match(source, /done:\s*\(result:\s*ComposerSendResult\)\s*=>\s*void/);
  assert.match(source, /if \(result\.accepted\)/);
  assert.match(source, /if \(inputText\.value === draft\) inputText\.value = ""/);
  assert.match(source, /內容已保留/);
});

test("composer exposes readiness and ASR errors to assistive technology", () => {
  assert.match(source, /canSend\?:\s*boolean/);
  assert.match(source, /asrSupported\?:\s*boolean/);
  assert.match(source, /role="alert"/);
  assert.match(source, /:aria-describedby=/);
});
