import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../ControlBar.vue"), "utf8");

test("control bar shows the character's name and status, not an engineering console title", () => {
  // 來賓看到的是角色，不是「控制台」（2026-10-06 UX 審查）。
  assert.doesNotMatch(source, /控制台/);
  assert.match(source, /\{\{ title \|\| "openVman" \}\}/);
  assert.match(source, /label: "聆聽中"/);
  assert.match(source, /label: "思考中"/);
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

test("visitor mode hides settings and unlocks only on a long press of the title", () => {
  assert.match(source, /v-if="settingsVisible !== false"/);
  // 長按才解鎖：來賓隨手點幾下不會誤觸（2026-10-06 改掉連點三下）。
  assert.match(source, /@pointerdown="startHold"/);
  assert.match(source, /@pointerup="cancelHold"/);
  assert.match(source, /emit\("unlockRequest"\)/);
  assert.doesNotMatch(source, /titleTap/);
});
