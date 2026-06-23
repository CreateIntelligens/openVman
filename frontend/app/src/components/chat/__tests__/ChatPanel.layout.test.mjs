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

test("mobile chat collapses when empty and caps the message viewport when populated", () => {
  const mobileMarker = "@media (max-width: 40rem) {";

  assert.match(cssBlockAfter(mobileMarker, ".chat-panel"), /flex:\s*none;/);
  assert.match(cssBlockAfter(mobileMarker, ".chat-panel"), /height:\s*auto;/);
  assert.match(cssBlockAfter(mobileMarker, ".chat-messages"), /flex:\s*none;/);
  assert.match(cssBlockAfter(mobileMarker, ".chat-messages"), /max-height:\s*40svh;/);
  assert.match(cssBlockAfter(mobileMarker, ".chat-messages:empty"), /padding-block:\s*0;/);
});
