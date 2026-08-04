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

test("custom select delegates keyboard and screen-reader behavior to native select", () => {
  const source = readFileSync(
    resolve(__dirname, "../controls/CustomSelect.vue"),
    "utf8",
  );

  assert.match(source, /<select/);
  assert.match(source, /<option/);
  assert.doesNotMatch(source, /role="listbox"/);
});
