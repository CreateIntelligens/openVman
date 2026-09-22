import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { transformSync } from "esbuild";

const __dirname = dirname(fileURLToPath(import.meta.url));
const modulePath = resolve(__dirname, "../storageUtils.ts");

/**
 * 真的把模組跑起來，而不是比對原始碼字串。這幾個案例要驗的是「例外有沒有被
 * 吞掉」，regex 看不出這件事。
 */
async function loadStorageUtils(localStorage) {
  const sharedStoragePath = resolve(__dirname, "../../../../shared/speech/storage.ts");
  const sharedStorageSource = readFileSync(sharedStoragePath, "utf-8");
  const { code: sharedCode } = transformSync(sharedStorageSource, {
    loader: "ts",
    format: "esm",
    target: "es2022",
  });
  const sharedStorageUrl = `data:text/javascript;base64,${Buffer.from(sharedCode).toString("base64")}`;

  const source = readFileSync(modulePath, "utf-8").replace(
    /from\s+["']@shared\/speech["'];?/,
    `from "${sharedStorageUrl}";`,
  );
  const { code } = transformSync(source, {
    loader: "ts",
    format: "esm",
    target: "es2022",
  });
  // window 要在呼叫期間都在，模組裡每個函式都會先檢查 typeof window。
  globalThis.window = { localStorage };
  // scopeId 是模組層級狀態，每個案例要拿到自己的一份，否則綁定會互相污染。
  return await import(
    `data:text/javascript;base64,${Buffer.from(
      `${code}\n//${Math.random()}`,
    ).toString("base64")}`
  );
}

/** 無痕模式：讀寫都直接拋，連 getItem 都不給碰。 */
function throwingStorage() {
  return {
    getItem() {
      throw new DOMException("denied", "SecurityError");
    },
    setItem() {
      throw new DOMException("quota", "QuotaExceededError");
    },
    removeItem() {
      throw new DOMException("denied", "SecurityError");
    },
  };
}

function memoryStorage(seed = {}) {
  const map = new Map(Object.entries(seed));
  return {
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => map.set(key, String(value)),
    removeItem: (key) => map.delete(key),
    snapshot: () => Object.fromEntries(map),
  };
}

test("reading a preference falls back instead of throwing when storage is blocked", async () => {
  const { readPref } = await loadStorageUtils(throwingStorage());
  assert.equal(readPref("avatar.reply_mode", "fast"), "fast");
});

test("writing a preference swallows the quota error", async () => {
  const { writePref } = await loadStorageUtils(throwingStorage());
  // 寫入是從 store 的 watch() 裡呼叫的，拋出去會竄進 Vue 的響應式系統。
  assert.doesNotThrow(() => writePref("avatar.reply_mode", "deep"));
});

test("removing a preference clears the legacy key so the fallback cannot resurrect it", async () => {
  const storage = memoryStorage({
    "avatar.reply_mode": "deep",
    "avatar.reply_mode::acct-1": "standard",
  });
  const { setPrefScope, removePref, readPref } = await loadStorageUtils(storage);

  setPrefScope("acct-1");
  removePref("avatar.reply_mode");

  assert.deepEqual(storage.snapshot(), {});
  assert.equal(readPref("avatar.reply_mode", "fast"), "fast");
});

test("hasPref tells a chosen default apart from a value that was never stored", async () => {
  const storage = memoryStorage({ "avatar.background_id::acct-1": "dark" });
  const { setPrefScope, hasPref } = await loadStorageUtils(storage);

  setPrefScope("acct-1");
  assert.equal(hasPref("avatar.background_id"), true);
  assert.equal(hasPref("avatar.reply_mode"), false);
});

test("hasPref reports false instead of throwing when storage is blocked", async () => {
  const { hasPref } = await loadStorageUtils(throwingStorage());
  assert.equal(hasPref("avatar.background_id"), false);
});
