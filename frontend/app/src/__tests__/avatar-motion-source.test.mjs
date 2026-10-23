import assert from "node:assert/strict";
import { test } from "node:test";

import { motionSource, segments, validateMotionManifest } from "../../public/experiments/avatar-motion/motion-source.js";

const manifest = () => ({ id: "hciot-v1", fps: 25, frameCount: 800, width: 1080, height: 1920,
  segments: { idle: { start: 0, end: 8 }, thinking: { start: 8, end: 16 },
    greeting: { start: 16, end: 24 }, bye: { start: 24, end: 32 } } });

test("the new source uses a separate protected bundle and a neutral speaking base", () => {
  assert.match(motionSource.dataUrl, /^\/static\/characters\/0624\/motion-lab\/hciot-v1\//);
  assert.equal(segments.idle.clip, "waiting-command.mp4");
  assert.equal(segments.speaking.clip, segments.idle.clip);
  assert.equal(segments.greeting.clip, "idle.mp4");
  assert.equal(segments.greeting.loop, false);
  assert.equal(segments.bye.loop, false);
});

test("a stale or differently indexed bundle is rejected before initializing WASM", () => {
  assert.doesNotThrow(() => validateMotionManifest(manifest()));
  assert.throws(() => validateMotionManifest({ ...manifest(), id: "0624" }), /版本/);
  assert.throws(() => validateMotionManifest({ ...manifest(), fps: 30 }), /規格/);
  assert.throws(() => validateMotionManifest({ ...manifest(), frameCount: 799 }), /規格/);
  const shifted = manifest();
  shifted.segments.thinking.start = 8.04;
  assert.throws(() => validateMotionManifest(shifted), /時間軸/);
});
