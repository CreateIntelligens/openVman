import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const storeSource = readFileSync(resolve(__dirname, "../useSettingsStore.ts"), "utf8");
const storageSource = readFileSync(resolve(__dirname, "../../utils/storageUtils.ts"), "utf8");

test("avatar settings persist the selected project id", () => {
  assert.match(storageSource, /PROJECT_ID:\s*"avatar\.project_id"/);
  assert.match(storeSource, /projectId:\s*readPref\(STORAGE_KEYS\.PROJECT_ID,\s*"default"\)/);
  assert.match(storeSource, /watch\(\(\) => state\.projectId,\s*\(v\) => writePref\(STORAGE_KEYS\.PROJECT_ID,\s*v\)\)/);
});

test("avatar settings default to Standard text chat mode", () => {
  assert.match(storeSource, /voiceMode:\s*readPref\(STORAGE_KEYS\.VOICE_MODE,\s*"text"\) as 'live' \| 'text'/);
  assert.doesNotMatch(storeSource, /voiceMode:\s*readPref\(STORAGE_KEYS\.VOICE_MODE,\s*"live"\)/);
});
