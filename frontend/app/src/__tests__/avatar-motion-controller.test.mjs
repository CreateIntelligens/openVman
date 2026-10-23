import assert from "node:assert/strict";
import { test } from "node:test";

import { MotionSegmentPlayer, seekVideo, waitForDecodedFrame } from "../../public/experiments/avatar-motion/motion-controller.js";

const segments = { idle: { start: 0.16, end: 1.68 }, thinking: { start: 2.68, end: 4.4 }, speaking: { start: 6.4, end: 8.04 } };
let nextAnimation = 0;
const animations = new Map();
globalThis.requestAnimationFrame = (callback) => { const id = ++nextAnimation; animations.set(id, callback); return id; };
globalThis.cancelAnimationFrame = (id) => animations.delete(id);

class Video extends EventTarget {
  duration = 8.16;
  readyState = 4;
  paused = false;
  seeking = false;
  time = 0;
  emitSeeked = true;
  listeners = 0;
  addEventListener(...args) { this.listeners += 1; super.addEventListener(...args); }
  removeEventListener(...args) { this.listeners -= 1; super.removeEventListener(...args); }
  get currentTime() { return this.time; }
  set currentTime(value) {
    this.time = value;
    this.seeking = true;
    if (this.emitSeeked) queueMicrotask(() => { this.seeking = false; this.dispatchEvent(new Event("seeked")); });
  }
  pause() { this.paused = true; }
  async play() { this.paused = false; }
  requestVideoFrameCallback(callback) { return setTimeout(callback, 1); }
  cancelVideoFrameCallback(id) { clearTimeout(id); }
}

test("rapid overlapping requests only commit the last segment and release seek listeners", async () => {
  const video = new Video(), changes = [];
  const player = new MotionSegmentPlayer(video, segments, { onChange: (state) => changes.push(state) });
  try {
    const results = await Promise.all([player.setState("thinking"), player.setState("speaking"), player.setState("idle")]);
    assert.deepEqual(results, [false, false, true]);
    assert.deepEqual(changes, ["idle"]);
    assert.equal(video.currentTime, segments.idle.start);
    assert.equal(player.transitioning, false);
    assert.equal(video.listeners, 0);
  } finally { player.dispose(); }
});

test("the reveal gate ignores a decoded frame from the old segment and cancels cleanly", async () => {
  const video = new Video(), callbacks = new Map(); let id = 0;
  video.requestVideoFrameCallback = callback => { callbacks.set(++id, callback); return id; };
  video.cancelVideoFrameCallback = token => callbacks.delete(token);
  const controller = new AbortController(); let resolved = false;
  const pending = waitForDecodedFrame(video, controller.signal, segments.idle).then(() => { resolved = true; });
  const old = callbacks.get(id); callbacks.delete(id); old(0, { mediaTime: 3 });
  await Promise.resolve();
  assert.equal(resolved, false);
  assert.equal(callbacks.size, 1);
  const next = callbacks.get(id); callbacks.delete(id); next(0, { mediaTime: .2 });
  await pending;
  assert.equal(resolved, true);
  assert.equal(callbacks.size, 0);
  const abort = new AbortController();
  const cancelled = waitForDecodedFrame(video, abort.signal, segments.thinking);
  abort.abort();
  await assert.rejects(cancelled, { name: 'AbortError' });
  assert.equal(callbacks.size, 0);
});

test("idle and speech sharing a base clip keep the current pose and decoder running", async () => {
  const video = new Video(), changes = [], handoffs = [];
  const player = new MotionSegmentPlayer(video, { ...segments, speaking: segments.idle }, {
    reuseContinuousSegment: true,
    beforeSeek: state => handoffs.push(state), onChange: state => changes.push(state),
  });
  try {
    await player.setState("idle");
    video.time = .96;
    await player.setState("speaking");
    assert.equal(player.video, video);
    assert.equal(video.currentTime, .96);
    assert.equal(video.paused, false);
    await player.setState("idle");
    assert.equal(video.currentTime, .96);
    assert.deepEqual(handoffs, ["idle"]);
    assert.deepEqual(changes, ["idle", "speaking", "idle"]);
    video.time = segments.idle.end - .01;
    player.tick();
    await new Promise(resolve => setTimeout(resolve, 15));
    assert.equal(player.loops, 1);
    assert.equal(video.currentTime, segments.idle.start);
  } finally { player.dispose(); }
});

test("a loop seeks within the same original bundle without changing segment state", async () => {
  const video = new Video(), player = new MotionSegmentPlayer(video, segments);
  try {
    await player.setState("thinking");
    video.time = 4.39;
    player.tick();
    await new Promise((resolve) => setTimeout(resolve, 15));
    assert.equal(player.state, "thinking");
    assert.equal(player.loops, 1);
    assert.equal(video.currentTime, 2.68);
    assert.equal(player.transitions.at(-1).reason, "loop");
  } finally { player.dispose(); }
});

test("a one-shot action reaches its end and returns to idle without looping", async () => {
  const video = new Video(), changes = [];
  const player = new MotionSegmentPlayer(video, {
    ...segments, bye: { start: 6.4, end: 8.16, loop: false, next: "idle" },
  }, { onChange: (state) => changes.push(state) });
  try {
    await player.setState("bye");
    video.time = 8.13;
    player.tick();
    await new Promise((resolve) => setTimeout(resolve, 15));
    assert.equal(player.state, "idle");
    assert.equal(player.loops, 0);
    assert.deepEqual(changes, ["bye", "idle"]);
    assert.equal(player.transitions.at(-1).reason, "complete");
    assert.equal(video.currentTime, segments.idle.start);
  } finally { player.dispose(); }
});

test("dispose cancels a pending seek without playing a stale request", async () => {
  const video = new Video();
  video.emitSeeked = false;
  const player = new MotionSegmentPlayer(video, segments);
  const pending = player.setState("speaking");
  player.dispose();
  assert.equal(await pending, false);
  assert.equal(video.paused, true);
  assert.equal(video.listeners, 0);
  assert.deepEqual(player.errors, []);
});

test("seek timeout rejects and cleans listeners instead of remaining busy forever", async () => {
  const video = new Video();
  video.emitSeeked = false;
  await assert.rejects(seekVideo(video, 2.68, new AbortController().signal, 10), /逾時/);
  assert.equal(video.listeners, 0);
});

test("segment bounds cannot read past the original data/video timeline", () => {
  assert.throws(() => new MotionSegmentPlayer(new Video(), { ...segments, speaking: { start: 7, end: 9 } }), /無效/);
  assert.throws(() => new MotionSegmentPlayer(new Video(), { ...segments, idle: { start: -1, end: 1 } }), /無效/);
});

test("decoder/playback rejection is reported and releases transition state", async () => {
  const video = new Video();
  video.play = async () => { throw new Error("playback blocked"); };
  const player = new MotionSegmentPlayer(video, segments);
  try {
    await assert.rejects(player.setState("thinking"), /playback blocked/);
    assert.equal(player.transitioning, false);
    assert.equal(player.errors.length, 1);
    assert.equal(video.listeners, 0);
  } finally { player.dispose(); }
});
