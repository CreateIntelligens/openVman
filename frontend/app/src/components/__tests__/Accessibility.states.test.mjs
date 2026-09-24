import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

test("status notifications announce changes and have a touch-sized close action", () => {
  const source = readFileSync(resolve(__dirname, "../StatusToast.vue"), "utf8");

  assert.match(source, /:role="toast\.persistent \? 'alert' : 'status'"/);
  assert.match(source, /:aria-live="toast\.persistent \? 'assertive' : 'polite'"/);
  assert.match(source, /aria-label="關閉通知"/);
  assert.match(source, /min-width:\s*2\.75rem/);
  assert.match(source, /min-height:\s*2\.75rem/);
});

test("custom select draws its own list with combobox semantics and keyboard support", () => {
  // 原生 <select> 點開的清單由作業系統畫，套不到主題樣式（使用者回報），所以自己畫；
  // 自己畫就得自己補上原生給的鍵盤操作與報讀資訊。
  const source = readFileSync(
    resolve(__dirname, "../controls/CustomSelect.vue"),
    "utf8",
  );

  assert.doesNotMatch(source.split("<script")[0], /<select/);
  assert.match(source, /role="combobox"/);
  assert.match(source, /:aria-expanded="open"/);
  assert.match(source, /:aria-controls="listboxId"/);
  assert.match(source, /:aria-activedescendant=/);
  assert.match(source, /role="listbox"/);
  assert.match(source, /role="option"/);
  assert.match(source, /:aria-selected="option\.value === modelValue"/);
  for (const key of ["Enter", "ArrowDown", "ArrowUp", "Home", "End", "Escape", "Tab"]) {
    assert.match(source, new RegExp(`'${key}'`), `缺少 ${key} 鍵處理`);
  }
  assert.match(source, /min-height:\s*2\.75rem/);
});
