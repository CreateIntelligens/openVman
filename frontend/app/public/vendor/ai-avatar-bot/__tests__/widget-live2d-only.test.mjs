import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../widget.html"), "utf8");

// 小助理只剩內建 Live2D（Haru）。後台角落的 MascotWidget 仍用 model／fit 參數載入這一頁。
test("widget boots Live2D directly from the model and fit params", () => {
  assert.match(source, /const MODEL_URL = CFG\.get\('model'\) \|\|/);
  assert.match(source, /haru_greeter_t03\.model3\.json/);
  assert.match(source, /const FIT_MODE = CFG\.get\('fit'\) \|\| 'half'/);
  assert.match(source, /\} else \{\s*bootAvatar\(\);\s*\}/);
  assert.match(source, /model = await Live2DModel\.from\(MODEL_URL\)/);
});

test("widget keeps the host mouth protocol and parent notifications", () => {
  assert.match(source, /if \(d\.ns !== 'avatar-widget-host'\) return;/);
  assert.match(source, /if \(d\.type === 'mouth'\) driveMouth\(d\.volume\);/);
  assert.match(source, /if \(d\.type === 'mouth-stop'\) stopMouth\(\);/);
  for (const type of ["ready", "screenshot", "error", "close"]) {
    assert.match(source, new RegExp(`postToParent\\('${type}'`));
  }
});

test("widget no longer ships the VRM or video-character engines", () => {
  assert.doesNotMatch(source, /importmap/);
  assert.doesNotMatch(source, /three|vrm|VRM/);
  assert.doesNotMatch(source, /OpenVmanAvatar|bootVideo|CHARACTER_ID/);
  assert.doesNotMatch(source, /setEngine|bootEngine/);
});
