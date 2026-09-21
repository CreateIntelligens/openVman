import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../App.vue"), "utf8");

test("the chat picks an engine instead of always using the browser one", () => {
  assert.match(source, /useServerAsr/);
  assert.match(source, /const useBrowserAsr = computed/);
  // 切換要看使用者選的引擎，不是寫死用 asr。
  assert.match(source, /useBrowserAsr\.value \? asr : serverAsr/);
});

test("browser recognition needs both the capability check and the account choice", () => {
  // 只看 isSupported 會漏掉「使用者沒選瀏覽器辨識」的情況，反過來只看選擇
  // 則會在不支援的瀏覽器上整個壞掉。
  assert.match(source, /myAsrProvider\.value === BROWSER_ASR && asr\.isSupported\.value/);
});

test("a terminal browser error falls back to the server engine", () => {
  // isSupported 是 true 但使用者拒絕麥克風時，瀏覽器辨識照樣不能用，那要
  // 當場換引擎而不是叫使用者改用鍵盤。
  assert.match(source, /BROWSER_FALLBACK_ERRORS/);
  for (const code of ["not-allowed", "audio-capture", "service-not-allowed"]) {
    assert.match(source, new RegExp(`"${code}"`));
  }
});

test("a one-off failure does not switch the engine away", () => {
  // no-speech 是這一次沒講話，重試即可；把它算進 fallback 會讓使用者無故
  // 被換掉引擎。
  const block = source.slice(
    source.indexOf("BROWSER_FALLBACK_ERRORS = new Set"),
    source.indexOf("]);", source.indexOf("BROWSER_FALLBACK_ERRORS = new Set")),
  );
  assert.doesNotMatch(block, /no-speech/);
  assert.doesNotMatch(block, /start-failed/);
});

test("the account's engine is read from the backend, not assumed", () => {
  assert.match(source, /fetchMyAsrProvider/);
  // 讀不到偏好不該讓使用者不能講話。
  assert.match(source, /fetchMyAsrProvider\(\)[\s\S]{0,200}\.catch\(/);
});
