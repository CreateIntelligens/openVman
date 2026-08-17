import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import ts from "typescript";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../src/idleLipSyncBypass.ts"), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ES2022,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText;
const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`;
const { installIdleLipSyncBypass } = await import(moduleUrl);

const CANVAS_WIDTH = 1080;
const CANVAS_HEIGHT = 1920;
const PATCH_RECT = [452, 486, 232, 232];

function createFakeCanvas() {
  const calls = [];
  const context = {
    globalAlpha: 1,
    clearRect(_x, _y, width, height) {
      calls.push(`clearRect ${width}x${height}`);
    },
    drawImage(...args) {
      calls.push(`drawImage ${args.length} alpha=${context.globalAlpha}`);
    },
  };
  const canvas = {
    getContext: () => context,
    height: CANVAS_HEIGHT,
    width: CANVAS_WIDTH,
  };
  return { calls, canvas, context };
}

function renderVendorFrame(context) {
  context.clearRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
  context.drawImage({}, 0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
  context.clearRect(...PATCH_RECT);
  context.drawImage({}, 0, 0, 180, 180, ...PATCH_RECT);
}

test("idle lip-sync bypass preserves native idle frames and vendor speaking frames", () => {
  let now = 0;
  const { calls, canvas, context } = createFakeCanvas();
  const originalClearRect = context.clearRect;
  const originalDrawImage = context.drawImage;
  const bypass = installIdleLipSyncBypass(canvas, () => now);

  assert.ok(bypass);
  renderVendorFrame(context);
  assert.deepEqual(calls, [
    `clearRect ${CANVAS_WIDTH}x${CANVAS_HEIGHT}`,
    "drawImage 5 alpha=1",
  ]);

  calls.length = 0;
  bypass.beginSpeaking();
  now = 100;
  renderVendorFrame(context);
  assert.deepEqual(calls, [
    `clearRect ${CANVAS_WIDTH}x${CANVAS_HEIGHT}`,
    "drawImage 5 alpha=1",
    "drawImage 9 alpha=0.5",
  ]);
  assert.equal(context.globalAlpha, 1);

  calls.length = 0;
  now = 1_000;
  renderVendorFrame(context);
  assert.deepEqual(calls, [
    `clearRect ${CANVAS_WIDTH}x${CANVAS_HEIGHT}`,
    "drawImage 5 alpha=1",
    "clearRect 232x232",
    "drawImage 9 alpha=1",
  ]);

  calls.length = 0;
  bypass.endSpeaking();
  now = 1_400;
  renderVendorFrame(context);
  assert.deepEqual(calls, [
    `clearRect ${CANVAS_WIDTH}x${CANVAS_HEIGHT}`,
    "drawImage 5 alpha=1",
    "drawImage 9 alpha=0.6",
  ]);

  calls.length = 0;
  now = 2_000;
  bypass.beginSpeaking();
  now = 2_100;
  renderVendorFrame(context);
  assert.deepEqual(calls, [
    `clearRect ${CANVAS_WIDTH}x${CANVAS_HEIGHT}`,
    "drawImage 5 alpha=1",
    "drawImage 9 alpha=0.5",
  ]);

  calls.length = 0;
  context.clearRect(10, 20, 30, 40);
  context.drawImage({}, 0, 0, 180, 180, 50, 60, 30, 40);
  assert.deepEqual(calls, ["clearRect 30x40", "drawImage 9 alpha=1"]);

  calls.length = 0;
  bypass.resetSpeaking();
  renderVendorFrame(context);
  assert.deepEqual(calls, [
    `clearRect ${CANVAS_WIDTH}x${CANVAS_HEIGHT}`,
    "drawImage 5 alpha=1",
  ]);

  bypass.restore();
  assert.equal(context.clearRect, originalClearRect);
  assert.equal(context.drawImage, originalDrawImage);
});
