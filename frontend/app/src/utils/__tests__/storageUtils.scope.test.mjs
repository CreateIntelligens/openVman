import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const __dirname = dirname(fileURLToPath(import.meta.url));
const srcRoot = resolve(__dirname, "../..");
const read = (p) => readFileSync(resolve(srcRoot, p), "utf-8");

test("preferences are keyed per account", () => {
  const source = read("utils/storageUtils.ts");
  assert.match(source, /function scopedKey\(key: string\): string \{/);
  assert.match(source, /scopeId \? `\$\{key\}::\$\{scopeId\}` : key/);
  // 寫入一定要落在綁定後的鍵上，否則兩個帳號還是會互蓋。
  assert.match(source, /setItem\(scopedKey\(key\), value\)/);
});

test("an account with no stored value inherits the pre-scoping one", () => {
  // 既有使用者升級後不該被重設，但之後的寫入要落在自己的鍵上。
  const source = read("utils/storageUtils.ts");
  assert.match(
    source,
    /const scoped = window\.localStorage\.getItem\(scopedKey\(key\)\)[\s\S]{0,160}getItem\(key\) \?\? fallback/,
  );
});

test("the store rebinds when the account resolves after startup", () => {
  // store 是模組層級單例，在登入完成前就初始化了。
  const store = read("stores/useSettingsStore.ts");
  assert.match(store, /export function bindSettingsToAccount\(accountId: string\): void/);
  assert.match(store, /Object\.assign\(state, loadState\(\)\)/);
  // 同一個帳號重複綁定要短路，不要無謂地重讀。
  assert.match(store, /if \(currentPrefScope\(\) === \(accountId \|\| ""\)\) return/);

  const app = read("App.vue");
  assert.match(app, /bindSettingsToAccount\(accountId\)/);
  // immediate 讓「還原既有工作階段」也會綁定，不是只有互動式登入。
  assert.match(app, /\{ immediate: true \}/);
});
