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

test("camera button explains itself when vision service is unavailable", () => {
  assert.match(source, /cameraDisabled\?:\s*boolean/);
  assert.match(source, /攝影機功能未啟用（視覺辨識服務未開啟）/);
  assert.match(source, /:title="cameraTitle"/);
  assert.match(source, /:aria-label="cameraTitle"/);
});

test("settings button can stay enabled while renderer actions are disabled", () => {
  assert.match(source, /settingsDisabled\?:\s*boolean/);
  assert.match(source, /class="control-btn settings-btn"[\s\S]*?:disabled="settingsDisabled"/);
  assert.match(source, /:disabled="disabled \|\| cameraDisabled"/);
});
