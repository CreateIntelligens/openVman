import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../App.vue"), "utf8");

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

const globalMobileMarker = "@media (max-width: 68.75rem) {\n  html, body, #app";
const scopedMobileMarker = "@media (max-width: 68.75rem) {\n  .app-shell";

test("mobile layout allows vertical page scroll instead of clipping the console", () => {
  assert.match(cssBlockAfter(globalMobileMarker, "html, body, #app"), /overflow-y:\s*auto;/);
  assert.match(cssBlockAfter(scopedMobileMarker, ".app-shell"), /height:\s*auto;/);
  assert.match(cssBlockAfter(scopedMobileMarker, ".app-shell"), /min-height:\s*100dvh;/);
});

test("mobile layout preserves avatar stage height instead of compressing it after chat grows", () => {
  assert.match(cssBlockAfter(scopedMobileMarker, ".stage-card"), /flex:\s*none;/);
  assert.match(
    cssBlockAfter(scopedMobileMarker, ".stage-card"),
    /height:\s*clamp\(16rem,\s*48svh,\s*28rem\);/,
  );
});

test("mobile console uses content height instead of reserving an empty viewport", () => {
  assert.match(cssBlockAfter(scopedMobileMarker, ".console-column"), /min-height:\s*0;/);
  assert.match(cssBlockAfter(scopedMobileMarker, ".console-column"), /^\s*height:\s*auto;/m);
});
