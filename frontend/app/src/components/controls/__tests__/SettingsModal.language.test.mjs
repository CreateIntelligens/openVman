import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const read = (p) => readFileSync(resolve(__dirname, p), "utf8");
const modal = read("../SettingsModal.vue");

test("the settings modal offers an answer-language select with no-lock and the five languages", () => {
  assert.match(modal, />回答語言</);
  assert.match(modal, /v-model="draftLockedLanguage"/);
  assert.match(modal, /\{ value: '', label: '不指定' \}/);
  const types = read("../../../types/lockedLanguage.ts");
  for (const label of ["中文", "English", "Español", "日本語", "한국어"]) assert.match(types, new RegExp(label));
});

test("changing only the language still applies and reconnects, and a URL language locks the select", () => {
  assert.match(modal, /if \(draftLockedLanguage\.value !== \(props\.lockedLanguage \?\? ''\)\) \{\s*emit\('lockedLanguageChange'/);
  assert.match(modal, /draftLockedLanguage\.value !== \(props\.lockedLanguage \?\? ''\) \|\|/);
  assert.match(modal, /:disabled="disabled \|\| Boolean\(urlLockedLanguage\)"/);
});

test("lockedLanguage is a persisted preference with its own key", () => {
  const store = read("../../../stores/useSettingsStore.ts");
  assert.match(store, /lockedLanguage: normalizeLockedLanguage\(readPref\(STORAGE_KEYS\.LOCKED_LANGUAGE, ""\)\)/);
  assert.match(store, /lockedLanguage: STORAGE_KEYS\.LOCKED_LANGUAGE/);
  assert.match(read("../../../composables/useAvatarSettings.ts"), /saveSettings\(\{ lockedLanguage: normalizeLockedLanguage\(language\) \}\)/);
});

test("chat requests and the greeting read the language with URL priority", () => {
  const conversation = read("../../../composables/useAvatarConversation.ts");
  assert.match(conversation, /language: \(\) => activeLockedLanguage\(settings\.lockedLanguage\)/);
  assert.match(read("../../../App.vue"), /activeLockedLanguage\(settings\.lockedLanguage\)/);
});

test("the reply bubble shows a catalogue link only for http(s) urls, in a new tab", () => {
  const panel = read("../../chat/ChatPanel.vue");
  assert.match(panel, /v-if="safeHttpUrl\(msg\.catalogUrl\)"/);
  assert.match(panel, /:href="safeHttpUrl\(msg\.catalogUrl\) \|\| undefined"\s+target="_blank"\s+rel="noopener noreferrer"\s*>\s*查看型錄/);
});
