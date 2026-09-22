import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../AsrButton.vue"), "utf8");

test("microphone has distinct hover, focus, pressed, listening, and disabled states", () => {
  assert.match(source, /@media \(hover: hover\)/);
  assert.match(source, /\.asr-btn:focus-visible/);
  assert.match(source, /\.asr-btn:active:not\(:disabled\)/);
  assert.match(source, /\.asr-btn--active/);
  assert.match(source, /\.asr-btn:disabled/);
});

test("listening indicator stays inside the button instead of expanding over the composer", () => {
  assert.match(source, /class="asr-btn__status"/);
  assert.doesNotMatch(source, /asr-btn__pulse/);
  assert.doesNotMatch(source, /scale\(1\.5\)/);
});

test("listening is animated so the user can tell the microphone is live", () => {
  // 靜態變色不夠：使用者回報「點了看不到反饋，不知道有沒有收音」。
  assert.match(source, /\.asr-btn--active \{\s*animation: asr-breathe/);
  // 動態用 inset，留在按鈕裡面。
  assert.match(source, /@keyframes asr-breathe[\s\S]{0,200}inset/);
  assert.match(source, /prefers-reduced-motion: reduce/);
});

test("waiting for the server transcript is a visible, non-clickable state", () => {
  // 伺服器引擎是整段上傳，停止收音到出字之間有幾秒空窗。
  assert.match(source, /isTranscribing\?: boolean/);
  assert.match(source, /:disabled="disabled \|\| isTranscribing \|\| isSupported === false"/);
  assert.match(source, /class="asr-btn__spinner"/);
  // 辨識中不能套一般 disabled 的淡化，否則看起來像壞掉。
  assert.match(source, /\.asr-btn--transcribing:disabled \{\s*opacity: 1/);
});

test("the button reflects whichever engine is actually recording", () => {
  // 先前畫面永遠綁瀏覽器辨識，選了伺服器引擎時按下去毫無反應。
  const app = readFileSync(resolve(__dirname, "../../../App.vue"), "utf8");
  assert.match(app, /if \(useBrowserAsr\.value\) return asr;\s*return vadAvailable\.value \? vadAsr : serverAsr;/);
  assert.match(app, /:asr-listening="activeAsr\.isListening\.value"/);
  assert.match(app, /:asr-supported="activeAsr\.isSupported\.value"/);
  assert.match(app, /:asr-transcribing="serverAsr\.isTranscribing\.value \|\| vadAsr\.isTranscribing\.value"/);
  assert.doesNotMatch(app, /:asr-listening="asr\.isListening\.value"/);
});
