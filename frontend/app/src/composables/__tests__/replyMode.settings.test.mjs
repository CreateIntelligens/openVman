import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const __dirname = dirname(fileURLToPath(import.meta.url));
const srcRoot = resolve(__dirname, "../..");
const read = (p) => readFileSync(resolve(srcRoot, p), "utf-8");

test("the avatar app defaults to fast, where the wait matters more than breadth", () => {
  const types = read("types/replyMode.ts");
  assert.match(types, /DEFAULT_REPLY_MODE: ReplyMode = 'fast'/);

  // store 讀不到偏好時也要落在 fast。
  const store = read("stores/useSettingsStore.ts");
  assert.match(store, /replyMode: normalizeReplyMode\(readPref\(STORAGE_KEYS\.REPLY_MODE, "fast"\)\)/);
});

test("an unrecognised stored mode falls back instead of sticking", () => {
  const types = read("types/replyMode.ts");
  assert.match(types, /REPLY_MODES\.some\(/);
  assert.match(types, /: DEFAULT_REPLY_MODE/);
});

test("the chosen mode is read per request, not captured once", () => {
  // 用 getter 才能讓使用者改完設定的下一句就生效。
  const chat = read("composables/useAvatarChat.ts");
  assert.match(chat, /replyMode\?: \(\) => string/);
  assert.match(chat, /mode: options\.replyMode\?\.\(\) \?\? ''/);

  const app = read("App.vue");
  assert.match(app, /replyMode: \(\) => settings\.replyMode/);
});

test("the mode is persisted and offered in settings", () => {
  const store = read("stores/useSettingsStore.ts");
  assert.match(store, /watch\(\(\) => state\.replyMode/);

  const modal = read("components/controls/SettingsModal.vue");
  assert.match(modal, /回覆深度/);
  assert.match(modal, /v-for="option in REPLY_MODES"/);
});

test("changing only the reply mode still applies", () => {
  // 它一度被塞進 voiceMode 的 if 裡，只改深度就不會送出。
  const modal = read("components/controls/SettingsModal.vue");
  assert.match(
    modal,
    /if \(draftReplyMode\.value !== props\.replyMode\) \{\s*emit\('replyModeChange'/,
    "replyModeChange 必須有自己的判斷式",
  );
  assert.match(
    modal,
    /draftReplyMode\.value !== props\.replyMode\n\)/,
    "dirty 判斷要納入回覆深度，否則套用鈕不會啟用",
  );
});
