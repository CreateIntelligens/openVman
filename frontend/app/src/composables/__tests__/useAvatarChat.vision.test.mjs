import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../useAvatarChat.ts"), "utf8");

test("exposes sendVisualInput and a default vision endpoint", () => {
  assert.match(source, /export const DEFAULT_VISION_ENDPOINT = ['"]\/api\/v1\/vision\/describe['"]/);
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

test("visual input state can be reset in live and text modes", () => {
  assert.match(source, /export const DEFAULT_VISION_RESET_ENDPOINT = ['"]\/api\/v1\/vision\/reset['"]/);
  assert.match(source, /function resetVisualInput\(\):\s*Promise<void>/);
  assert.match(source, /event:\s*['"]client_camera_reset['"]/);
  assert.match(source, /options\.visionResetEndpoint \?\? DEFAULT_VISION_RESET_ENDPOINT/);
  assert.match(source, /\bresetVisualInput,/);
});

test("visual signal state is exposed and updated from camera frame status", () => {
  assert.match(source, /export interface VisualState/);
  assert.match(source, /const visualState = ref<VisualState>/);
  assert.match(source, /case ['"]server_camera_frame_status['"]:/);
  assert.match(source, /applyVisualState\(data\.visual_state\)/);
  assert.match(source, /visualState:\s*readonly\(visualState\)/);
});

test("vision replies are routed through onUtteranceComplete", () => {
  // sendVisualInput text path must reuse the same reply pipeline as chat.
  assert.match(source, /onUtteranceComplete\?\.\(/);
});
