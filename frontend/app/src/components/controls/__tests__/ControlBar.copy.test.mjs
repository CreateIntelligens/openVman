import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../ControlBar.vue"), "utf8");

test("control bar presents one merged virtual human console title", () => {
  assert.match(source, /<h2>openVman 控制台<\/h2>/);
  assert.doesNotMatch(source, /Reception Console/);
  assert.doesNotMatch(source, /control-bar__eyebrow/);
});

test("immersive camera mode exposes a camera size slider", () => {
  assert.match(source, /cameraPreviewScale\?:\s*number/);
  assert.match(source, /cameraPreviewScaleChange:\s*\[scale:\s*number\]/);
  assert.match(source, /v-if="cameraActive && immersive"/);
  assert.match(source, /type="range"/);
  assert.match(source, /min="0\.85"/);
  assert.match(source, /max="1\.35"/);
});

test("camera button disappears when the vision service is unavailable", () => {
  // 先前是 disabled + tooltip 說明。但一個永遠按不下去的按鈕只是雜訊，
  // 使用者也無從得知「未啟用」是暫時的還是永久的。改成整個不顯示。
  assert.match(source, /v-if="cameraAvailable"/);
  assert.match(source, /cameraAvailable\?:\s*boolean/);
  assert.doesNotMatch(source, /cameraDisabled/);
  assert.match(source, /:title="cameraTitle"/);
  assert.match(source, /:aria-label="cameraTitle"/);
});

test("settings button can stay enabled while renderer actions are disabled", () => {
  assert.match(source, /settingsDisabled\?:\s*boolean/);
  assert.match(source, /class="control-btn settings-btn"[\s\S]*?:disabled="settingsDisabled"/);
  assert.match(source, /:disabled="disabled"/);
});
