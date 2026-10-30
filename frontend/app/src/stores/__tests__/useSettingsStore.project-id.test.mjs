import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const storeSource = readFileSync(resolve(__dirname, "../useSettingsStore.ts"), "utf8");
const storageSource = readFileSync(resolve(__dirname, "../../utils/storageUtils.ts"), "utf8");
const backgroundTypeSource = readFileSync(resolve(__dirname, "../../types/avatarBackground.ts"), "utf8");

test("avatar settings persist the selected project id", () => {
  assert.match(storageSource, /PROJECT_ID:\s*"avatar\.project_id"/);
  assert.match(storeSource, /projectId:\s*readPref\(STORAGE_KEYS\.PROJECT_ID,\s*"default"\)/);
  assert.match(storeSource, /projectId: STORAGE_KEYS\.\w+/);
});

test("avatar settings default to Standard text chat mode", () => {
  assert.match(storeSource, /voiceMode:\s*normalizeVoiceMode\(readPref\(STORAGE_KEYS\.VOICE_MODE,\s*"text"\)\)/);
  assert.doesNotMatch(storeSource, /voiceMode:\s*readPref\(STORAGE_KEYS\.VOICE_MODE,\s*"live"\)/);
});

test("avatar settings persist stage background preferences", () => {
  assert.match(storageSource, /BACKGROUND_ID:\s*"avatar\.background_id"/);
  assert.match(storageSource, /BACKGROUND_URL:\s*"avatar\.background_url"/);
  assert.match(storageSource, /BACKGROUND_FIT:\s*"avatar\.background_fit"/);
  assert.match(storeSource, /backgroundId:\s*normalizeAvatarBackgroundId\(readPref\(STORAGE_KEYS\.BACKGROUND_ID,\s*"dark"\)\)/);
  assert.match(storeSource, /backgroundUrl:\s*readPref\(STORAGE_KEYS\.BACKGROUND_URL,\s*""\)/);
  assert.match(storeSource, /backgroundFit:\s*normalizeAvatarBackgroundFit\(readPref\(STORAGE_KEYS\.BACKGROUND_FIT,\s*"cover"\)\)/);
  assert.match(storeSource, /backgroundId: STORAGE_KEYS\.\w+/);
  assert.match(storeSource, /backgroundUrl: STORAGE_KEYS\.\w+/);
  assert.match(storeSource, /backgroundFit: STORAGE_KEYS\.\w+/);
});

test("avatar settings persist camera preview scale", () => {
  assert.match(storageSource, /CAMERA_PREVIEW_SCALE:\s*"avatar\.camera_preview_scale"/);
  assert.match(storeSource, /function normalizeCameraPreviewScale\(value: string\): number/);
  assert.match(storeSource, /cameraPreviewScale:\s*normalizeCameraPreviewScale\(readPref\(STORAGE_KEYS\.CAMERA_PREVIEW_SCALE,\s*"1"\)\)/);
  assert.match(storeSource, /cameraPreviewScale: STORAGE_KEYS\.\w+/);
});

// 3D（VRM）舞台已拿掉：舊的 render mode／VRM 偏好不再讀寫，伺服器回來的舊值也被忽略
// （實際開場行為見 useAdminHandoff.test.mjs 的 legacy 3D 測試）。
test("settings no longer carry a render mode or VRM avatar", () => {
  assert.doesNotMatch(storageSource, /RENDER_MODE|VRM_AVATAR_ID/);
  assert.doesNotMatch(storeSource, /renderMode|vrmAvatarId/);
});

test("only saveSettings writes preferences; bootstrap choices stay in memory", () => {
  // 以前每個欄位都有 watch 寫回，開場的清空與退回也被當成使用者的選擇存下去。
  assert.doesNotMatch(storeSource, /\bwatch\(/);
  assert.match(storeSource, /export function saveSettings\(patch: Partial<SettingsState>\): void/);
});

test("avatar settings accept uploaded background ids", () => {
  assert.match(backgroundTypeSource, /type UploadedAvatarBackgroundId = `uploaded:\$\{string\}`/);
  assert.match(backgroundTypeSource, /isUploadedAvatarBackgroundId/);
  assert.match(backgroundTypeSource, /if \(isUploadedAvatarBackgroundId\(value\)\)/);
});

test("avatar settings normalize background display modes", () => {
  assert.match(backgroundTypeSource, /export type AvatarBackgroundFit = "cover" \| "contain" \| "repeat"/);
  assert.match(backgroundTypeSource, /AVATAR_BACKGROUND_FITS = \["cover", "contain", "repeat"\]/);
  assert.match(backgroundTypeSource, /function normalizeAvatarBackgroundFit\(value: string\): AvatarBackgroundFit/);
});
