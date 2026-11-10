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
  assert.match(source, /:disabled="!isListening && \(disabled \|\| isTranscribing \|\| isSupported === false\)"/);
  assert.match(source, /class="asr-btn__spinner"/);
  // 辨識中不能套一般 disabled 的淡化，否則看起來像壞掉。
  assert.match(source, /\.asr-btn--transcribing:disabled \{\s*opacity: 1/);
});

test("the button reflects whichever engine is actually recording", () => {
  // 先前畫面永遠綁瀏覽器辨識，選了伺服器引擎時按下去毫無反應。
  const app = readFileSync(resolve(__dirname, "../../../App.vue"), "utf8") + "\n" + readFileSync(resolve(__dirname, "../../../composables/useAvatarVoiceInput.ts"), "utf8");
  assert.match(app, /if \(useBrowserAsr\.value\) return asr;\s*if \(useStreamAsrEngine\.value\) return streamAsr;\s*return vadAvailable\.value \? vadAsr : serverAsr;/);
  // 啟動中也算「按下了」，按鈕要有反應，但實際收音狀態由提示文字區分。
  assert.match(app, /:asr-listening="voiceSessionOn"/);
  assert.match(app, /:asr-supported="activeAsr\.isSupported\.value"/);
  assert.match(app, /:asr-transcribing="serverAsr\.isTranscribing\.value \|\| vadAsr\.isTranscribing\.value"/);
  assert.doesNotMatch(app, /:asr-listening="asr\.isListening\.value"/);
});

test("a listening microphone can always be stopped", () => {
  // 連續說話時每句都在上傳辨識；之前這段時間按鈕被鎖，麥克風停不掉。
  const button = source.indexOf('v-else-if="isTranscribing"');
  const stopIcon = source.indexOf('v-if="isListening"');
  assert.ok(stopIcon > 0 && button > stopIcon, "收音中要顯示停止，不是辨識中的轉圈");
  assert.match(source, /'asr-btn--transcribing': isTranscribing && !isListening/);
});

test("the composer does not tell a listening user to wait", () => {
  const panel = readFileSync(new URL("../ChatPanel.vue", import.meta.url), "utf8");
  const label = panel.match(/const asrButtonLabel = computed\(\(\) => \{([\s\S]*?)\n\}\)/);
  assert.ok(label[1].indexOf("!props.asrListening") < label[1].indexOf("asrTranscribing"));
  assert.match(panel, /if \(props\.asrPaused\) return "/);
  assert.match(panel, /v-if="asrListening && !asrPaused"/);
});
