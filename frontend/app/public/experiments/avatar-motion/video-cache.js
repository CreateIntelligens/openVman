import { seekVideo } from "./motion-controller.js";

/** Paused decoders share one Blob URL and preserve the original media timeline. */
export class MotionVideoCache {
  constructor(active, segments, { createVideo, maxEntries = 3 } = {}) {
    this.active = active;
    this.segments = segments;
    this.maxEntries = Math.max(1, Math.min(maxEntries, Object.keys(segments).length));
    this.createVideo = createVideo;
    this.slots = [];
    this.hits = 0;
    this.misses = 0;
    this.disposed = false;
    this.deferredRefill = null;
  }

  async warm() {
    // Sequential setup bounds decoder pressure during the initial load.
    for (const state of Object.keys(this.segments).slice(0, this.maxEntries)) {
      if (this.disposed) throw new DOMException("取消", "AbortError");
      const video = await this.createVideo(this.active.src);
      if (this.disposed) {
        releaseVideo(video);
        throw new DOMException("取消", "AbortError");
      }
      const slot = { video, state: null, ready: false, abort: null, pending: null };
      this.slots.push(slot);
      await this.prepare(slot, state);
    }
  }

  prepare(slot, state) {
    slot.abort?.abort();
    const abort = new AbortController();
    slot.abort = abort;
    slot.state = state;
    slot.ready = false;
    slot.video.pause();
    const pending = seekVideo(slot.video, this.segments[state].start, abort.signal)
      .then(() => {
        if (!abort.signal.aborted) slot.ready = true;
      }).finally(() => {
        if (slot.pending === pending) slot.pending = null;
      });
    // Background refill failures are retried by acquire; they never reject unhandled.
    pending.catch(() => {});
    slot.pending = pending;
    return pending;
  }

  async acquire(state, signal) {
    if (signal.aborted || this.disposed) throw new DOMException("取消", "AbortError");
    this.refill();
    if (!this.segments[state]) throw new Error(`未知狀態：${state}`);
    let slot = this.slots.find((entry) => entry.state === state);
    const cacheHit = Boolean(slot?.ready);
    if (cacheHit) this.hits += 1;
    else {
      this.misses += 1;
      slot ??= this.slots.find((entry) => !entry.pending) ?? this.slots[0];
      if (!slot) throw new Error("影片快取尚未準備");
      if (slot.state !== state || !slot.pending) this.prepare(slot, state);
    }
    if (slot.pending) await abortable(slot.pending, signal);
    if (signal.aborted) throw new DOMException("取消", "AbortError");
    // Another request may have reassigned a bounded cache slot while we waited.
    if (slot.state !== state || !slot.ready) return this.acquire(state, signal);
    return { video: slot.video, cacheHit };
  }

  activate(video, state, { deferRefill = false } = {}) {
    if (this.disposed) throw new DOMException("取消", "AbortError");
    const slot = this.slots.find((entry) => entry.video === video);
    if (!slot?.ready || slot.state !== state) throw new Error("影片快取已失效");
    const previous = this.active;
    this.active = video;
    previous.pause();
    slot.video = previous;
    slot.ready = false;
    slot.state = null;
    // Recycle the old decoder at this segment's entry while the new one plays.
    // The next loop can then swap without seeking the active video.
    this.deferredRefill = { slot, state };
    if (!deferRefill) this.refill();
  }

  refill() {
    const pending = this.deferredRefill;
    this.deferredRefill = null;
    if (!this.disposed && pending) return this.prepare(pending.slot, pending.state);
  }

  snapshot() {
    return { hits: this.hits, misses: this.misses, entries: this.slots.length,
      maxEntries: this.maxEntries, pending: this.slots.filter((slot) => slot.pending).length };
  }

  dispose({ keepActive = false } = {}) {
    this.disposed = true;
    this.deferredRefill = null;
    for (const slot of this.slots) slot.abort?.abort();
    for (const video of new Set([...(keepActive ? [] : [this.active]), ...this.slots.map((slot) => slot.video)])) {
      releaseVideo(video);
    }
    this.slots.length = 0;
  }
}

function releaseVideo(video) {
  video.pause();
  video.removeAttribute("src");
  video.load();
  video.remove();
}

function abortable(promise, signal) {
  return new Promise((resolve, reject) => {
    const aborted = () => reject(new DOMException("取消", "AbortError"));
    signal.addEventListener("abort", aborted, { once: true });
    promise.then(resolve, reject).finally(() => signal.removeEventListener("abort", aborted));
    if (signal.aborted) aborted();
  });
}
