import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const __dirname = dirname(fileURLToPath(import.meta.url));
const read = (p) => readFileSync(resolve(__dirname, "../..", p), "utf-8");
const bootstrap = read("composables/useAvatarBootstrap.ts");
const app = read("App.vue");

function body(source, signature) {
  const start = source.indexOf(signature);
  assert.notEqual(start, -1, `找不到 ${signature}`);
  return source.slice(start, source.indexOf("\n  }\n", start));
}

// 使用者回報：重整之後知識庫、人物、語音引擎、聲音全部變回預設。根因是開場
// 抓清單時直接套帳號預設，把 store 從 localStorage 還原的選擇蓋掉。

test("bootstrap picks from what the user saved, not from the live field", () => {
  // 開場會先把欄位清空；偏好一律取 savedSettings()，清空或退回都不會影響下次。
  assert.match(body(bootstrap, "async function fetchProjects()"), /const savedProjectId = savedSettings\(\)\.projectId/);
  assert.match(body(bootstrap, "async function fetchTtsProviders()"), /savedSettings\(\)/);
  assert.match(body(bootstrap, "async function fetchVrmAvatars()"), /preferSaved\(\s*savedSettings\(\)\.vrmAvatarId,/);
  assert.match(app, /preferSaved\(\s*savedSettings\(\)\.characterId,/);
});

test("a chosen background is not overwritten by the account default", () => {
  const fn = body(bootstrap, "async function fetchBackgrounds()");
  // 背景預設值是 "dark"，光看值分不出選過沒有，所以看有沒有存過。
  assert.ok(
    fn.indexOf("hasPref(STORAGE_KEYS.BACKGROUND_ID)") < fn.indexOf('accountDefault("background_id"'),
  );
});

test("a saved value that is no longer offered falls back instead of sticking", () => {
  // 清單是權威：被收回授權或刪掉的選擇不能留在畫面上。
  assert.match(bootstrap, /return saved && isValid\(saved\) \? saved : fallback/);
});

test("no bootstrap path applies an account default without checking the saved value", () => {
  // 每個 accountDefault() 呼叫都要嘛包在 preferSaved 裡、要嘛前面有 hasPref
  // 或 resolveTtsVoiceSelection 先看存的那一對。新增欄位時漏掉這件事，這個 bug 就會長回來。
  const calls = [...(bootstrap + app).matchAll(/accountDefault\("(\w+)"/g)].map((m) => m[1]);
  assert.deepEqual(
    [...new Set(calls)].sort(),
    ["background_id", "character_id", "mascot_id", "project_id", "voice_id", "voice_provider"],
    "多了新的帳號預設欄位：確認它有讓存的值優先，再更新這份清單",
  );
});
