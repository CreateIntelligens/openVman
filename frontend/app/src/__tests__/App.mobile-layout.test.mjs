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

const kioskStackedMarker = "@media (max-width: 68.75rem) {\n  .app-shell";
const phoneGlobalMarker = "@media (max-width: 48rem) {\n  html, body, #app";
const phoneScopedMarker = "@media (max-width: 48rem) {\n  .app-shell";

test("layout renders controls before avatar and chat for stacked RWD", () => {
  const controlsIndex = source.indexOf("<ControlBar");
  const stageIndex = source.indexOf('<section class="stage-panel">');
  const chatIndex = source.indexOf("<ChatPanel");

  assert.notEqual(controlsIndex, -1, "missing ControlBar");
  assert.notEqual(stageIndex, -1, "missing stage panel");
  assert.notEqual(chatIndex, -1, "missing ChatPanel");
  assert.ok(controlsIndex < stageIndex, "controls should render before avatar stage");
  assert.ok(stageIndex < chatIndex, "avatar stage should render before chat panel");
  assert.doesNotMatch(source, /class="console-column"/);
});

test("avatar stage does not render a separate title block from the controls", () => {
  assert.doesNotMatch(source, /class="stage-hero"/);
  assert.doesNotMatch(source, /class="stage-panel__intro"/);
});

test("desktop layout keeps avatar left and controls with chat on the right", () => {
  assert.match(cssBlockAfter(".kiosk-layout", ".kiosk-layout"), /display:\s*grid;/);
  assert.match(
    cssBlockAfter(".kiosk-layout", ".kiosk-layout"),
    /grid-template-areas:\s*"stage controls"\s*"stage chat";/,
  );
  assert.match(cssBlockAfter(".stage-panel", ".stage-panel"), /grid-area:\s*stage;/);
  assert.match(cssBlockAfter(".control-area", ".control-area"), /grid-area:\s*controls;/);
  assert.match(cssBlockAfter(".chat-area", ".chat-area"), /grid-area:\s*chat;/);
});

test("kiosk RWD stacks the layout while keeping the page viewport locked", () => {
  assert.doesNotMatch(source, /@media \(max-width: 68\.75rem\) \{\s*html, body, #app/);
  assert.match(cssBlockAfter(kioskStackedMarker, ".app-shell"), /height:\s*100dvh;/);
  assert.match(cssBlockAfter(kioskStackedMarker, ".app-shell"), /overflow:\s*hidden;/);
  assert.match(cssBlockAfter(kioskStackedMarker, ".kiosk-layout"), /display:\s*flex;/);
  assert.match(cssBlockAfter(kioskStackedMarker, ".kiosk-layout"), /flex-direction:\s*column;/);
  assert.match(cssBlockAfter(kioskStackedMarker, ".kiosk-layout"), /overflow:\s*hidden;/);
  assert.match(cssBlockAfter(kioskStackedMarker, ".control-area"), /order:\s*1;/);
  assert.match(cssBlockAfter(kioskStackedMarker, ".stage-panel"), /order:\s*2;/);
  assert.match(cssBlockAfter(kioskStackedMarker, ".chat-area"), /order:\s*3;/);
  assert.match(cssBlockAfter(kioskStackedMarker, ".chat-area"), /flex:\s*1 1 0;/);
  assert.match(cssBlockAfter(kioskStackedMarker, ".chat-area"), /overflow:\s*hidden;/);
});

test("mobile layout allows vertical page scroll instead of clipping the console", () => {
  assert.match(cssBlockAfter(phoneGlobalMarker, "html, body, #app"), /overflow-y:\s*auto;/);
  assert.match(cssBlockAfter(phoneScopedMarker, ".app-shell"), /height:\s*auto;/);
  assert.match(cssBlockAfter(phoneScopedMarker, ".app-shell"), /min-height:\s*100dvh;/);
});

test("mobile layout preserves avatar stage height instead of compressing it after chat grows", () => {
  assert.match(cssBlockAfter(phoneScopedMarker, ".stage-card"), /flex:\s*none;/);
  assert.match(
    cssBlockAfter(phoneScopedMarker, ".stage-card"),
    /height:\s*clamp\(16rem,\s*48svh,\s*28rem\);/,
  );
});

test("mobile console uses content height instead of reserving an empty viewport", () => {
  assert.match(cssBlockAfter(phoneScopedMarker, ".chat-area"), /flex:\s*none;/);
  assert.match(cssBlockAfter(phoneScopedMarker, ".chat-area"), /^\s*height:\s*auto;/m);
});
