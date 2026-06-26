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
  assert.match(storeSource, /watch\(\(\) => state\.projectId,\s*\(v\) => writePref\(STORAGE_KEYS\.PROJECT_ID,\s*v\)\)/);
});

test("avatar settings default to Standard text chat mode", () => {
  assert.match(storeSource, /voiceMode:\s*readPref\(STORAGE_KEYS\.VOICE_MODE,\s*"text"\) as 'live' \| 'text'/);
  assert.doesNotMatch(storeSource, /voiceMode:\s*readPref\(STORAGE_KEYS\.VOICE_MODE,\s*"live"\)/);
});

test("avatar settings persist stage background preferences", () => {
  assert.match(storageSource, /BACKGROUND_ID:\s*"avatar\.background_id"/);
  assert.match(storageSource, /BACKGROUND_URL:\s*"avatar\.background_url"/);
  assert.match(storageSource, /BACKGROUND_FIT:\s*"avatar\.background_fit"/);
  assert.match(storeSource, /backgroundId:\s*normalizeAvatarBackgroundId\(readPref\(STORAGE_KEYS\.BACKGROUND_ID,\s*"dark"\)\)/);
  assert.match(storeSource, /backgroundUrl:\s*readPref\(STORAGE_KEYS\.BACKGROUND_URL,\s*""\)/);
  assert.match(storeSource, /backgroundFit:\s*normalizeAvatarBackgroundFit\(readPref\(STORAGE_KEYS\.BACKGROUND_FIT,\s*"cover"\)\)/);
  assert.match(storeSource, /watch\(\(\) => state\.backgroundId,\s*\(v\) => writePref\(STORAGE_KEYS\.BACKGROUND_ID,\s*v\)\)/);
  assert.match(storeSource, /watch\(\(\) => state\.backgroundUrl,\s*\(v\) => writePref\(STORAGE_KEYS\.BACKGROUND_URL,\s*v\)\)/);
  assert.match(storeSource, /watch\(\(\) => state\.backgroundFit,\s*\(v\) => writePref\(STORAGE_KEYS\.BACKGROUND_FIT,\s*v\)\)/);
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
