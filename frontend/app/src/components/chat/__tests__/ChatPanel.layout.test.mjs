import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../ChatPanel.vue"), "utf8");

function cssBlock(selector) {
  const start = source.indexOf(`${selector} {`);
  assert.notEqual(start, -1, `missing CSS block for ${selector}`);
  const bodyStart = source.indexOf("{", start);
  const bodyEnd = source.indexOf("\n}", bodyStart);
  assert.notEqual(bodyEnd, -1, `missing CSS block end for ${selector}`);
  return source.slice(bodyStart + 1, bodyEnd);
}

function cssBlockAfter(marker, selector) {
  const markerStart = source.indexOf(marker);
  assert.notEqual(markerStart, -1, `missing marker ${marker}`);
  const start = source.indexOf(`${selector} {`, markerStart);
  assert.notEqual(start, -1, `missing CSS block for ${selector}`);
  const bodyStart = source.indexOf("{", start);
  const bodyEnd = source.indexOf("\n  }", bodyStart);
  assert.notEqual(bodyEnd, -1, `missing CSS block end for ${selector}`);
  return source.slice(bodyStart + 1, bodyEnd);
}

test("chat panel fills the console column while messages scroll internally", () => {
  assert.match(cssBlock(".chat-panel"), /flex:\s*1;/);
  assert.match(cssBlock(".chat-messages"), /overflow-y:\s*auto;/);
});

test("chat chrome does not shrink when messages grow", () => {
  assert.match(
    source,
    /\.chat-panel__header,\s*\.chat-input-bar\s*{[\s\S]*flex-shrink:\s*0;/,
  );
});

test("stacked RWD chat caps the message viewport instead of growing the page", () => {
  const mobileMarker = "@media (max-width: 48rem) {";

  assert.match(cssBlockAfter(mobileMarker, ".chat-panel"), /flex:\s*none;/);
  assert.match(cssBlockAfter(mobileMarker, ".chat-panel"), /height:\s*auto;/);
  assert.match(cssBlockAfter(mobileMarker, ".chat-messages"), /flex:\s*none;/);
  assert.match(cssBlockAfter(mobileMarker, ".chat-messages"), /max-height:\s*40svh;/);
  assert.match(
    cssBlockAfter(mobileMarker, ".chat-messages:has(.chat-messages__content:empty)"),
    /padding-block:\s*0;/,
  );
});

test("assistant media is responsive and served from the active project", () => {
  assert.match(source, /msg\.imageId/);
  assert.match(source, /project_id: message\.projectId \|\| "default"/);
  assert.match(source, /開啟相關連結/);
  assert.match(cssBlock(".chat-msg__media img"), /max-width:\s*100%;/);
  assert.match(cssBlock(".chat-msg__media img"), /object-fit:\s*contain;/);
});

test("send button styles do not leak into the microphone child component", () => {
  assert.match(source, /class="chat-send-btn"/);
  assert.match(source, /\.chat-send-btn\s*\{/);
  assert.doesNotMatch(source, /\.chat-input-bar button\s*\{/);
});

test("the composer says whether the microphone is live, and how to send", () => {
  // 使用者回報過「點了看不到反饋，不知道有沒有收音」。提示寫在輸入框裡，
  // 那是按下麥克風後眼睛會看的地方。
  assert.match(source, /:placeholder="composerPlaceholder"/);
  assert.match(source, /收音中…講完請再按一次麥克風送出/);
  assert.match(source, /收音中…請直接說話/);
  assert.match(source, /辨識中，請稍候…/);
  // 兩種引擎的操作方式不同，提示要跟著引擎走。
  assert.match(source, /props\.asrEngine === "server"/);
});

test("the listening status reaches assistive tech", () => {
  assert.match(source, /class="composer-status" role="status" aria-live="polite"/);
  // display: none 會連螢幕閱讀器一起擋掉，狀態區不能用它。
  const rule = source.slice(source.indexOf(".composer-status {"));
  assert.doesNotMatch(rule.slice(0, rule.indexOf("}")), /display:\s*none/);
});
