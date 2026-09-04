import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const __dirname = dirname(fileURLToPath(import.meta.url));
const runtimeSource = readFileSync(
  resolve(__dirname, "../useOpenVmanAvatarRuntime.ts"),
  "utf-8",
);

/**
 * 取出某個函式的內容（從 `function <name>` 到下一個同縮排的 `  }`）。
 * 這些測試檢查的是 WASM 記憶體的配置/釋放配對，靜態檢查就足夠，
 * 也避開了在 node --test 裡跑 TypeScript 的麻煩。
 */
function functionBody(source, name) {
  const start = source.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `找不到函式 ${name}`);
  const end = source.indexOf("\n  }", start);
  assert.notEqual(end, -1, `找不到函式 ${name} 的結尾`);
  return source.slice(start, end);
}

test("every _malloc is paired with a _free in a finally block", () => {
  // 漏掉 _free 會讓 WASM heap 一路長大；loadCharacter 的症狀是例外指標
  // 每次重試都往上跳，pushAudio 則是講話時持續洩漏。
  const mallocCount = (runtimeSource.match(/_malloc\(/g) ?? []).length;
  const freeCount = (runtimeSource.match(/_free\(/g) ?? []).length;
  assert.equal(
    mallocCount,
    freeCount,
    `_malloc (${mallocCount}) 與 _free (${freeCount}) 數量必須相同`,
  );

  for (const name of ["loadCharacter", "pushAudio"]) {
    const body = functionBody(runtimeSource, name);
    if (!body.includes("_malloc(")) continue;
    assert.match(
      body,
      /finally\s*\{[^}]*_free\(/,
      `${name} 的 _free 必須放在 finally，否則例外會跳過它`,
    );
  }
});

test("pushAudio reads HEAPU8 only after allocating", () => {
  // heap 成長時 Emscripten 會換掉 HEAPU8，舊的 view 會被 detach。
  // 先讀 view 再 _malloc 就可能寫進一塊已經失效的記憶體。
  const body = functionBody(runtimeSource, "pushAudio");
  const mallocAt = body.indexOf("_malloc(");
  const heapAt = body.indexOf("HEAPU8");
  assert.ok(mallocAt !== -1 && heapAt !== -1);
  assert.ok(
    mallocAt < heapAt,
    "HEAPU8 必須在 _malloc 之後才讀取",
  );
});

test("pushAudio bails out when the allocation fails", () => {
  const body = functionBody(runtimeSource, "pushAudio");
  assert.match(
    body,
    /if \(!pointer\)/,
    "_malloc 回傳 0 代表配置失敗，必須提早返回而不是寫進位址 0",
  );
});

test("the canvas patch is restored when the last consumer unmounts", () => {
  // installIdleLipSyncBypass 換掉了 canvas 的 clearRect / drawImage。
  // 不還原的話，patch 和它的 closure 會跟著 canvas 一直活著。
  assert.match(runtimeSource, /activeConsumers \+= 1/);
  assert.match(runtimeSource, /idleLipSyncBypass\?\.restore\(\)/);
  assert.match(
    runtimeSource,
    /activeConsumers === 0/,
    "必須用引用計數，單例被多個元件共用時才不會提早拆掉",
  );
});

test("unmounting still clears queued audio", () => {
  assert.match(runtimeSource, /onUnmounted\(\(\) => \{[\s\S]*clearAudio\(\)/);
});
