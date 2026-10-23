import assert from "node:assert/strict";
import { test } from "node:test";

import { MotionSegmentPlayer } from "../../public/experiments/avatar-motion/motion-controller.js";
import { MotionVideoCache } from "../../public/experiments/avatar-motion/video-cache.js";

const segments = {
  idle: { start: 0.16, end: 1.68 },
  thinking: { start: 2.68, end: 4.4 },
  speaking: { start: 6.4, end: 8.04 },
};
const source = "blob:motion-original-timeline";

class Video extends EventTarget {
  duration = 8.16;
  readyState = 4;
  paused = false;
  seeking = false;
  autoSeek = true;
  time = 0;
  seeks = [];
  listeners = new Map();
  loads = 0;
  removals = 0;
  plays = 0;

  constructor(src = source) { super(); this.src = src; }
  addEventListener(type, listener, options) {
    const registered = this.listeners.get(type) ?? new Set();
    registered.add(listener);
    this.listeners.set(type, registered);
    super.addEventListener(type, listener, options);
  }
  removeEventListener(type, listener, options) {
    this.listeners.get(type)?.delete(listener);
    super.removeEventListener(type, listener, options);
  }
  get listenerCount() {
    return [...this.listeners.values()].reduce((count, listeners) => count + listeners.size, 0);
  }
  get currentTime() { return this.time; }
  set currentTime(value) {
    this.seeks.push(value);
    this.time = value;
    this.seeking = true;
    if (this.autoSeek) queueMicrotask(() => this.completeSeek());
  }
  completeSeek() { this.seeking = false; this.dispatchEvent(new Event("seeked")); }
  pause() { this.paused = true; }
  async play() { this.paused = false; this.plays += 1; }
  removeAttribute(name) { if (name === "src") this.src = ""; }
  load() { this.loads += 1; }
  remove() { this.removals += 1; }
}

function fixture(maxEntries = 2) {
  const active = new Video(), created = [], sources = [];
  const cache = new MotionVideoCache(active, segments, {
    maxEntries,
    createVideo: async (src) => {
      sources.push(src);
      const video = new Video(src);
      created.push(video);
      return video;
    },
  });
  return { cache, active, created, sources };
}

async function finishRefills(cache) {
  await Promise.all(cache.slots.map((slot) => slot.pending).filter(Boolean));
}

test("standby factories share the original Blob source and acquire ready entry frames as hits", async () => {
  const { cache, active, created, sources } = fixture();
  try {
    await cache.warm();
    assert.deepEqual(sources, [source, source]);
    assert.deepEqual(created.map((video) => video.currentTime), [0.16, 2.68]);
    assert.ok(created.every((video) => video.paused && video.listenerCount === 0));
    const idle = await cache.acquire("idle", new AbortController().signal);
    assert.equal(idle.cacheHit, true);
    assert.equal(idle.video, created[0]);
    assert.deepEqual(idle.video.seeks, [segments.idle.start]);
    assert.deepEqual(active.seeks, []);
    assert.deepEqual(cache.snapshot(), { hits: 1, misses: 0, entries: 2, maxEntries: 2, pending: 0 });
  } finally { cache.dispose(); }
});

test("deferred refill waits for the visible handoff to finish before seeking the outgoing decoder", async () => {
  const { cache, active } = fixture();
  try {
    await cache.warm();
    const next = await cache.acquire("thinking", new AbortController().signal);
    const priorSeeks = active.seeks.length;
    cache.activate(next.video, "thinking", { deferRefill: true });
    await Promise.resolve();
    assert.equal(active.paused, true);
    assert.equal(active.seeks.length, priorSeeks);
    assert.equal(cache.slots.find(slot => slot.video === active).ready, false);
    cache.refill();
    await finishRefills(cache);
    assert.equal(active.seeks.at(-1), segments.thinking.start);
    assert.equal(cache.slots.find(slot => slot.video === active).ready, true);
  } finally { cache.dispose(); }
});

test("activation recycles and seeks only the previous decoder while the ready decoder plays", async () => {
  const { cache, active } = fixture();
  try {
    await cache.warm();
    const prepared = await cache.acquire("thinking", new AbortController().signal);
    const entrySeeks = [...prepared.video.seeks];
    cache.activate(prepared.video, "thinking");
    await prepared.video.play();
    assert.equal(cache.active, prepared.video);
    assert.equal(prepared.video.paused, false);
    assert.deepEqual(prepared.video.seeks, entrySeeks);
    assert.equal(active.paused, true);
    assert.deepEqual(active.seeks, [segments.thinking.start]);
    await finishRefills(cache);

    const nextLoop = await cache.acquire("thinking", new AbortController().signal);
    assert.equal(nextLoop.video, active);
    assert.equal(nextLoop.cacheHit, true);
    cache.activate(nextLoop.video, "thinking");
    await finishRefills(cache);
    assert.deepEqual(nextLoop.video.seeks, [segments.thinking.start]);
  } finally { cache.dispose(); }
});

test("two standby decoders remain bounded when a third state evicts and refills an entry", async () => {
  const { cache, active, created } = fixture();
  try {
    await cache.warm();
    const speaking = await cache.acquire("speaking", new AbortController().signal);
    assert.equal(speaking.cacheHit, false);
    assert.equal(speaking.video.currentTime, segments.speaking.start);
    assert.equal(created.length, 2);
    assert.equal(cache.slots.length, 2);
    assert.ok(!cache.slots.some((slot) => slot.state === "idle"));
    const retained = await cache.acquire("thinking", new AbortController().signal);
    assert.equal(retained.cacheHit, true);
    const evicted = await cache.acquire("idle", new AbortController().signal);
    assert.equal(evicted.cacheHit, false);
    assert.equal(evicted.video.currentTime, segments.idle.start);
    assert.equal(created.length, 2);
    assert.deepEqual(active.seeks, []);
    assert.deepEqual(cache.snapshot(), { hits: 1, misses: 2, entries: 2, maxEntries: 2, pending: 0 });
  } finally { cache.dispose(); }
});

test("rapid cancelled requests cannot activate a stale decoder through the segment player", async () => {
  const oldRequestAnimationFrame = globalThis.requestAnimationFrame;
  const oldCancelAnimationFrame = globalThis.cancelAnimationFrame;
  const animations = new Map();
  let nextAnimation = 0;
  globalThis.requestAnimationFrame = (callback) => { const id = ++nextAnimation; animations.set(id, callback); return id; };
  globalThis.cancelAnimationFrame = (id) => animations.delete(id);
  const { cache, active, created } = fixture(1);
  let player;
  try {
    await cache.warm();
    const standby = created[0], activations = [], changes = [];
    standby.autoSeek = false;
    player = new MotionSegmentPlayer(active, segments, {
      acquireVideo: (state, signal) => cache.acquire(state, signal),
      activateVideo: (video, state) => { cache.activate(video, state); activations.push(state); },
      afterSeek: async () => {},
      onChange: (state) => changes.push(state),
    });
    const stale = player.setState("thinking");
    const current = player.setState("speaking");
    standby.completeSeek();
    assert.deepEqual(await Promise.all([stale, current]), [false, true]);
    await finishRefills(cache);
    assert.deepEqual(activations, ["speaking"]);
    assert.deepEqual(changes, ["speaking"]);
    assert.equal(cache.active, standby);
    assert.equal(standby.currentTime, segments.speaking.start);
    assert.equal(standby.plays, 1);
    assert.deepEqual(player.errors, []);
    assert.equal(standby.listenerCount, 0);
  } finally {
    player?.dispose();
    cache.dispose();
    globalThis.requestAnimationFrame = oldRequestAnimationFrame;
    globalThis.cancelAnimationFrame = oldCancelAnimationFrame;
  }
});

test("dispose cancels pending acquisition and releases every active and standby decoder listener", async () => {
  const { cache, active, created } = fixture();
  await cache.warm();
  const prepared = await cache.acquire("thinking", new AbortController().signal);
  active.autoSeek = false;
  cache.activate(prepared.video, "thinking");
  const pending = cache.acquire("thinking", new AbortController().signal);
  const rejected = assert.rejects(pending, { name: "AbortError" });
  assert.ok(active.listenerCount > 0);
  cache.dispose();
  await rejected;
  assert.equal(cache.snapshot().entries, 0);
  assert.equal(cache.snapshot().pending, 0);
  for (const video of [active, ...created]) {
    assert.equal(video.paused, true);
    assert.equal(video.src, "");
    assert.equal(video.loads, 1);
    assert.equal(video.removals, 1);
    assert.equal(video.listenerCount, 0);
  }
});

test("dispose during an in-flight decoder factory releases the late decoder without reviving the cache", async () => {
  const active = new Video(), late = new Video();
  let completeFactory;
  const cache = new MotionVideoCache(active, segments, {
    maxEntries: 1,
    createVideo: () => new Promise((resolve) => { completeFactory = resolve; }),
  });
  const warming = cache.warm();
  cache.dispose();
  completeFactory(late);
  try {
    await Promise.allSettled([warming]);
    assert.equal(cache.snapshot().entries, 0);
    assert.equal(late.src, "");
    assert.equal(late.removals, 1);
    assert.equal(late.listenerCount, 0);
  } finally { cache.dispose(); }
});

test("failed warm-up can release standbys while preserving the original active video for fallback", async () => {
  const active = new Video(), standby = new Video();
  let calls = 0;
  const cache = new MotionVideoCache(active, segments, {
    maxEntries: 2,
    createVideo: async () => {
      calls += 1;
      if (calls === 2) throw new Error("decoder unavailable");
      return standby;
    },
  });
  await assert.rejects(cache.warm(), /decoder unavailable/);
  cache.dispose({ keepActive: true });
  assert.equal(active.src, source);
  assert.equal(active.paused, false);
  assert.equal(active.loads, 0);
  assert.equal(active.removals, 0);
  assert.equal(standby.src, "");
  assert.equal(standby.removals, 1);
  assert.equal(standby.listenerCount, 0);
  assert.equal(cache.snapshot().entries, 0);
  await assert.rejects(cache.acquire("idle", new AbortController().signal), { name: "AbortError" });
  assert.throws(() => cache.activate(standby, "idle"), { name: "AbortError" });
});
