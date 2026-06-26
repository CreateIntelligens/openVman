import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(
  resolve(__dirname, "../useWebcamCapture.ts"),
  "utf8",
);

test("useWebcamCapture is a Vue composable using ref/onUnmounted", () => {
  assert.match(source, /export function useWebcamCapture\(/);
  assert.match(source, /from ['"]vue['"]/);
  assert.match(source, /onUnmounted\(/);
});

test("defaults match design: 1s / 640x480 / jpeg q0.7", () => {
  assert.match(source, /DEFAULT_INTERVAL_MS = 1000/);
  assert.match(source, /DEFAULT_WIDTH = 640/);
  assert.match(source, /DEFAULT_HEIGHT = 480/);
  assert.match(source, /DEFAULT_QUALITY = 0\.7/);
  assert.match(source, /image\/jpeg/);
});

test("start() uses getUserMedia and an interval capture loop", () => {
  assert.match(source, /getUserMedia\(\{[\s\S]*?video:\s*true[\s\S]*?\}\)/);
  assert.match(source, /setInterval\(/);
  assert.match(source, /toDataURL\(/);
});

test("stop() clears interval and stops media tracks", () => {
  assert.match(source, /clearInterval\(/);
  assert.match(source, /\.getTracks\(\)/);
  assert.match(source, /track\.stop\(\)/);
});

test("onFrame receives base64, mime type and timestamp", () => {
  assert.match(
    source,
    /type WebcamFrameHandler = \(\s*base64:\s*string,\s*mimeType:\s*string,\s*timestamp:\s*number,\s*\)\s*=>\s*void/s,
  );
  assert.match(source, /onFrame:\s*WebcamFrameHandler/);
});

test("exposes active/error/stream refs and start/stop", () => {
  assert.match(source, /active:\s*Ref<boolean>/);
  assert.match(source, /error:\s*Ref<string>/);
  assert.match(source, /stream:\s*Ref<MediaStream \| null>/);
  assert.match(source, /start:\s*\(\)\s*=>\s*Promise<void>/);
  assert.match(source, /stop:\s*\(\)\s*=>\s*void/);
});

test("surfaces a Traditional-Chinese error when unsupported", () => {
  assert.match(source, /攝影機/);
});
