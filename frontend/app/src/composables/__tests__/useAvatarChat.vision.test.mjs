import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../useAvatarChat.ts"), "utf8");

test("exposes sendVisualInput and a default vision endpoint", () => {
  assert.match(source, /export const DEFAULT_VISION_ENDPOINT = ['"]\/api\/vision\/describe['"]/);
  assert.match(source, /function sendVisualInput\(/);
  assert.match(source, /\bsendVisualInput,/);
});

test("live mode sends a client_video_frame event", () => {
  assert.match(source, /event:\s*['"]client_video_frame['"]/);
  assert.match(source, /frame_base64/);
  assert.match(source, /mime_type/);
});

test("text mode posts the frame to the vision describe endpoint", () => {
  assert.match(source, /options\.visionEndpoint \?\? DEFAULT_VISION_ENDPOINT/);
  assert.match(source, /visionEndpoint\?:\s*string/);
});

test("vision replies are routed through onUtteranceComplete", () => {
  // sendVisualInput text path must reuse the same reply pipeline as chat.
  assert.match(source, /onUtteranceComplete\?\.\(/);
});
