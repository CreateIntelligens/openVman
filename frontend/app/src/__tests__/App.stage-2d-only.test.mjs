import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
// 樣板在 App.vue，清單載入與舞台邏輯在幾個 composable；合起來看才是完整的畫面。
const source = [
  readFileSync(resolve(__dirname, "../App.vue"), "utf8"),
  readFileSync(resolve(__dirname, "../composables/useAvatarBootstrap.ts"), "utf8"),
  readFileSync(resolve(__dirname, "../composables/useAvatarStage.ts"), "utf8"),
  readFileSync(resolve(__dirname, "../composables/useAvatarConversation.ts"), "utf8"),
  readFileSync(resolve(__dirname, "../composables/useAvatarVoiceInput.ts"), "utf8"),
  readFileSync(resolve(__dirname, "../components/controls/SettingsModal.vue"), "utf8"),
].join("\n");

test("app does not mount any mascot widget", () => {
  assert.doesNotMatch(source, /class="mascot-widget"/);
  assert.doesNotMatch(source, /class="mascot-reopen-button"/);
  assert.doesNotMatch(source, /<MascotSwitcher/);
});

// 前台只剩 2D 影片角色舞台；3D（VRM）渲染模式與小助理清單都拿掉了。
test("stage has only the 2D video-character renderer", () => {
  assert.match(source, /<AvatarCanvas/);
  assert.doesNotMatch(source, /renderMode/);
  assert.doesNotMatch(source, /stage-avatar-frame|stageAvatar|StageAvatar/);
  assert.doesNotMatch(source, /vrm|VRM/);
  assert.doesNotMatch(source, /\/api\/v1\/avatar\/mascots/);
  assert.doesNotMatch(source, /mascotCatalog/);
});

test("main stage background sits behind the 2D renderer", () => {
  assert.match(source, /class="stage-background"/);
  assert.match(source, /:class="stageBackgroundClass"/);
  assert.match(source, /:style="stageBackgroundStyle"/);
  assert.match(source, /const stageBackgroundClass = computed/);
  assert.match(source, /const stageBackgroundStyle = computed/);
  assert.match(source, /isUploadedAvatarBackgroundId/);
});
