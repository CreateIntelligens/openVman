/** One active video/data bundle; segment boundaries keep original frame indices. */
export class MotionSegmentPlayer {
  constructor(video, segments, hooks = {}) {
    this.video = video;
    this.segments = segments;
    this.hooks = hooks;
    this.state = "idle";
    this.loops = 0;
    this.transitions = [];
    this.errors = [];
    this.transitioning = false;
    this.disposed = false;
    this.revision = 0;
    this.abort = null;
    for (const [name, segment] of Object.entries(segments)) {
      if (!Number.isFinite(segment.start) || !Number.isFinite(segment.end)
          || segment.start < 0 || segment.end - segment.start < 0.4
          || segment.end > video.duration + 0.001) {
        throw new Error(`無效的 ${name} 播放區間`);
      }
    }
    this.endTimer = undefined;
    this.tick = () => {
      if (this.disposed) return;
      this.checkSegmentEnd();
      this.animation = requestAnimationFrame(this.tick);
    };
    this.animation = requestAnimationFrame(this.tick);
  }

  checkSegmentEnd() {
    if (this.disposed || this.transitioning) return;
    const segment = this.segments[this.state];
    const video = this.video;
    // 結束在檔尾的片段若在最後一幀之間沒輪到檢查，影片會自行 ended 並轉成 paused；
    // ended 也算播到結尾，否則會永遠停在這一段。
    const playing = !video.paused || video.ended;
    if (!playing) return;
    const remaining = segment.end - video.currentTime;
    if (remaining > 0.04) {
      // 畫面更新變慢（重負載、低階機台）時 rAF 會晚很多才輪到，
      // 另依影片時間排計時器，準時在片段結尾前檢查。
      clearTimeout(this.endTimer);
      this.endTimer = setTimeout(() => this.checkSegmentEnd(),
        ((remaining - 0.04) / (video.playbackRate || 1)) * 1000);
      return;
    }
    clearTimeout(this.endTimer);
    // 停在片段最後一幀再交接：交接本身要時間，不停的話舊影片會播進下一段的影格。
    const held = !video.ended;
    if (held) video.pause();
    const once = segment.loop === false;
    void this.setState(once ? segment.next ?? "idle" : this.state, once ? "complete" : "loop")
      .then((changed) => { if (!changed && held) this.resumeHeld(video); })
      .catch((error) => {
        if (held) this.resumeHeld(video);
        this.hooks.onError?.(error);
      });
  }

  resumeHeld(video) {
    // 交接失敗或被取代時，若這支影片仍是目前的來源就恢復播放，不要卡在暫停。
    if (!this.disposed && !this.transitioning && this.video === video && video.paused) {
      void video.play()?.catch?.(() => {});
    }
  }

  async setState(next, reason = "manual") {
    if (this.disposed) throw new Error("播放器已關閉");
    const segment = this.segments[next];
    if (!segment) throw new Error(`未知狀態：${next}`);
    const current = this.segments[this.state];
    // Idle and speech can share a continuous base clip; changing the logical
    // state must not rewind its pose when audio starts or drains.
    if (this.hooks.reuseContinuousSegment && reason === "manual" && !this.transitioning && next !== this.state
        && segment.loop !== false && current.loop !== false
        && segment.start === current.start && segment.end === current.end) {
      this.state = next;
      this.hooks.onChange?.(next);
      return true;
    }
    const revision = ++this.revision;
    this.abort?.abort();
    const abort = new AbortController();
    this.abort = abort;
    const started = performance.now();
    this.transitioning = true;
    this.hooks.beforeSeek?.(next);
    try {
      let cacheHit = false;
      if (this.hooks.acquireVideo) {
        const cached = await this.hooks.acquireVideo(next, abort.signal);
        if (revision !== this.revision) return false;
        this.video = cached.video;
        cacheHit = cached.cacheHit;
        this.hooks.activateVideo(this.video, next);
      } else {
        this.video.pause();
        await seekVideo(this.video, segment.start, abort.signal);
      }
      if (revision !== this.revision) return false;
      await this.video.play();
      const prepared = performance.now();
      if (this.hooks.afterSeek) await this.hooks.afterSeek(next, abort.signal, this.video);
      else await waitForDecodedFrame(this.video, abort.signal, segment);
      if (revision !== this.revision) return false;
      this.state = next;
      if (reason === "loop") this.loops += 1;
      const finished = performance.now();
      this.transitions.push({ state: next, reason, cacheHit,
        prepareMs: Math.round(prepared - started), renderMs: Math.round(finished - prepared),
        ms: Math.round(finished - started) });
      if (this.transitions.length > 200) this.transitions.shift();
      this.hooks.onChange?.(next);
      return true;
    } catch (error) {
      if (abort.signal.aborted) return false;
      this.errors.push(String(error));
      throw error;
    } finally {
      if (revision === this.revision) this.transitioning = false;
    }
  }

  dispose() {
    this.disposed = true;
    this.revision += 1;
    this.abort?.abort();
    clearTimeout(this.endTimer);
    cancelAnimationFrame(this.animation);
    this.video.pause();
  }
}

export function seekVideo(video, target, signal, timeout = 4000) {
  if (signal.aborted) return Promise.reject(new DOMException("取消", "AbortError"));
  if (Math.abs(video.currentTime - target) < 0.01 && !video.seeking && video.readyState >= 2) {
    return Promise.resolve();
  }
  return new Promise((resolve, reject) => {
    const finish = (error) => {
      clearTimeout(timer);
      video.removeEventListener("seeked", seeked);
      video.removeEventListener("error", failed);
      signal.removeEventListener("abort", aborted);
      error ? reject(error) : resolve();
    };
    const seeked = () => {
      if (Math.abs(video.currentTime - target) < 0.09) finish();
    };
    const failed = () => finish(new Error("影片讀取失敗"));
    const aborted = () => finish(new DOMException("取消", "AbortError"));
    const timer = setTimeout(() => finish(new Error("影片跳轉逾時")), timeout);
    video.addEventListener("seeked", seeked);
    video.addEventListener("error", failed);
    signal.addEventListener("abort", aborted, { once: true });
    video.currentTime = target;
  });
}

export function waitForDecodedFrame(video, signal, segment) {
  return new Promise((resolve, reject) => {
    let callback, animation;
    const finish = (error) => {
      clearTimeout(timer);
      signal.removeEventListener("abort", aborted);
      if (callback !== undefined) video.cancelVideoFrameCallback?.(callback);
      if (animation !== undefined) cancelAnimationFrame(animation);
      error ? reject(error) : resolve();
    };
    const aborted = () => finish(new DOMException("取消", "AbortError"));
    const timer = setTimeout(() => finish(new Error("等待解碼畫面逾時")), 3000);
    signal.addEventListener("abort", aborted, { once: true });
    if (signal.aborted) return aborted();
    const presented = (_now, frame) => {
      if (signal.aborted) return aborted();
      const time = frame?.mediaTime ?? video.currentTime;
      const withinSegment = !segment || (time >= segment.start - 0.04 && time < segment.end);
      if (!video.seeking && video.readyState >= 2 && withinSegment) return finish();
      schedule();
    };
    const schedule = () => {
      if (video.requestVideoFrameCallback) callback = video.requestVideoFrameCallback(presented);
      else animation = requestAnimationFrame(presented);
    };
    schedule();
  });
}
