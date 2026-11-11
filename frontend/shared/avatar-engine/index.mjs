import { FramePlayer } from "./frame-player.mjs";
import { loadCharacter, repairTrackingJumps, validateLipFrame } from "./character-adapter.mjs";
import { StreamingPlaybackController } from "./inference/streaming-playback.mjs";

const interrupted = () => new DOMException("播放已取消", "AbortError");

export async function decodeRenderPayload(bytes) {
  let raw = bytes;
  if (bytes[0] === 0x1f && bytes[1] === 0x8b) {
    const stream = new Blob([bytes])
      .stream()
      .pipeThrough(new DecompressionStream("gzip"));
    raw = new Uint8Array(await new Response(stream).arrayBuffer());
  }
  const data = JSON.parse(new TextDecoder().decode(raw));
  if (
    data.schema !== "openvman.render.v2" ||
    data.geometrySource !== "mediapipe-video" ||
    data.frameRate !== 25 ||
    !Array.isArray(data.frameSize) ||
    data.frameSize.length !== 2 ||
    !data.frameSize.every((n) => Number.isInteger(n) && n > 0 && n <= 8192) ||
    !Array.isArray(data.frames) ||
    !data.frames.length ||
    !data.frames.every(
      (row) =>
        row && Array.isArray(row.region) && row.region.length === 4 &&
        row.region.every(Number.isFinite) &&
        row.region[0] >= 0 && row.region[1] >= 0 &&
        row.region[2] > row.region[0] && row.region[3] > row.region[1] &&
        row.region[2] <= data.frameSize[0] && row.region[3] <= data.frameSize[1] &&
        [row.outer, row.inner].every(ring =>
          Array.isArray(ring) && ring.length === 40 &&
          ring.every(value => Number.isFinite(value) && value >= 0 && value <= 180)),
    )
  ) {
    throw new Error("人物渲染資料不符，請重新產製角色素材");
  }
  try {
    data.frames.forEach(validateLipFrame);
  } catch {
    throw new Error("人物渲染資料不符，請重新產製角色素材");
  }
  return data;
}

/** One owner for inference, the audible sample clock, geometry and neutralization. */
export class AvatarEngine {
  static async create(options) {
    const engine = new AvatarEngine(options);
    try {
      await engine.initialize();
      return engine;
    } catch (error) {
      engine.dispose();
      throw error;
    }
  }

  constructor(options) {
    this.options = options;
    this.canvas = options.canvas;
    this.video = options.video || document.createElement("video");
    this.video.crossOrigin = "anonymous";
    this.video.muted = this.video.loop = this.video.playsInline = true;
    this.base = new URL(
      options.runtimeBaseUrl || "/avatar-engine/",
      location.href,
    ).href.replace(/\/?$/, "/");
    this.audioContext = new AudioContext({ sampleRate: 16000 });
    this.output = this.audioContext.createGain();
    this.output.gain.value = options.audioOutput === "silent" ? 0 : 1;
    this.output.connect(this.audioContext.destination);
    this.listeners = new Set();
    this.waiters = new Set();
    this.videoWaiters = new Set();
    this.queue = Promise.resolve();
    this.generation = 0;
    this.loadGeneration = 0;
    this.sequence = 0;
    this.sample = 0;
    this.state = "ready";
    this.error = null;
    this.disposed = false;
    this.speaking = false;
    this.handle = null;
    this.controller = new StreamingPlaybackController({
      audioContext: this.audioContext,
      outputNode: this.output,
      deferResume: true,
      createWorker: (url) => this.createWorker(url),
      onFrame: ({ bsVec, nextBsVec, stepPhase }) => {
        if (this.player) this.player.setControls(bsVec, nextBsVec, stepPhase);
      },
      onStateChange: (state, previous, details) =>
        this.stateChanged(state, previous, details),
    });
  }

  createWorker(url) {
    // Classic workers must be same-origin. The bootstrap imports CORS-served assets from the SDK origin.
    const base = new URL("./", url).href;
    this.workerBootstrap = URL.createObjectURL(
      new Blob(
        [
          `self.AVATAR_ENGINE_BASE=${JSON.stringify(base)};importScripts(${JSON.stringify(url)});`,
        ],
        { type: "text/javascript" },
      ),
    );
    return new Worker(this.workerBootstrap);
  }

  async initialize() {
    await this.controller.initialize({
      workerUrl: `${this.base}inference/streaming-worker.js`,
      modelPath: `${this.base}models/mouth-model.wasm`,
    });
    this.rig = await loadCharacter();
  }

  stateChanged(state, previous, details) {
    this.state = state;
    const speaking = ["playing", "rebuffering", "draining"].includes(state);
    if (speaking !== this.speaking) {
      this.speaking = speaking;
      this.options.onSpeakingChange?.(speaking);
    }
    if (state === "error") {
      this.error = new Error(details?.error || "人物推論失敗");
      this.options.onError?.(this.error);
    }
    for (const notify of [...this.waiters]) notify();
    for (const listener of [...this.listeners])
      listener(state, previous, details);
  }

  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  async prepare() {
    if (this.disposed) throw new Error("人物引擎已關閉");
    await this.audioContext.resume();
    if (this.audioContext.state !== "running")
      throw new Error("請點擊畫面以啟用語音播放");
  }

  async loadCharacter(base, { signal, payload, videoUrl } = {}) {
    if (this.disposed) throw new Error("人物引擎已關閉");
    this.loadAbort?.abort();
    for (const cancel of [...this.videoWaiters]) cancel();
    const operation = new AbortController();
    this.loadAbort = operation;
    const cancel = () => operation.abort();
    signal?.addEventListener("abort", cancel, { once: true });
    if (signal?.aborted) cancel();
    const requestSignal = operation.signal;
    // Pause first: stop() must not leave an easing mouth that nothing will paint again.
    this.player?.pause();
    this.stop();
    const revision = ++this.loadGeneration;
    try {
      let bytes = payload;
      if (!bytes) {
        const response = await fetch(`${base}/render_data.json.gz`, {
          signal: requestSignal,
        });
        if (!response.ok)
          throw new Error(
            `人物渲染資料載入失敗：${response.status}，請轉換或重新產製角色`,
          );
        bytes = new Uint8Array(await response.arrayBuffer());
      }
      const data = await decodeRenderPayload(bytes);
      if (
        requestSignal.aborted ||
        revision !== this.loadGeneration ||
        this.disposed
      )
        throw interrupted();
      this.video.src = videoUrl || `${base}/01.webm`;
      this.video.load();
      await this.waitForVideo(requestSignal);
      if (
        requestSignal.aborted ||
        revision !== this.loadGeneration ||
        this.disposed
      )
        throw interrupted();
      this.applyCharacterData(data);
      const player = this.player;
      await this.video.play();
      if (
        requestSignal.aborted ||
        revision !== this.loadGeneration ||
        this.disposed ||
        player !== this.player
      )
        throw interrupted();
      player.draw();
      player.start();
    } catch (error) {
      // A failed switch keeps the character already on screen alive, not frozen.
      if (revision === this.loadGeneration && !this.disposed) this.player?.start();
      throw error;
    } finally {
      signal?.removeEventListener("abort", cancel);
      if (this.loadAbort === operation) this.loadAbort = null;
    }
  }

  applyCharacterData(data) {
    if (this.disposed) throw new Error("人物引擎已關閉");
    this.player?.dispose({ keepVideo: true });
    const character = { ...this.rig, frames: repairTrackingJumps(data.frames) };
    [this.canvas.width, this.canvas.height] = data.frameSize;
    this.player = new FramePlayer(this.canvas, this.video, character);
    this.player.videoSource = this.options.videoSource;
    this.player.start();
  }

  waitForVideo(signal) {
    if (this.video.readyState >= 2) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const done = (error) => {
        clearTimeout(timeout);
        this.video.removeEventListener("loadeddata", ready);
        this.video.removeEventListener("error", failed);
        signal?.removeEventListener("abort", aborted);
        this.videoWaiters.delete(aborted);
        error ? reject(error) : resolve();
      };
      const ready = () => done();
      const failed = () => done(new Error("人物影片無法解碼"));
      const aborted = () => done(interrupted());
      const timeout = setTimeout(
        () => done(new Error("人物影片載入逾時")),
        15000,
      );
      this.videoWaiters.add(aborted);
      this.video.addEventListener("loadeddata", ready);
      this.video.addEventListener("error", failed);
      signal?.addEventListener("abort", aborted, { once: true });
      if (signal?.aborted) aborted();
    });
  }

  serial(operation) {
    if (this.disposed) return Promise.reject(new Error("人物引擎已關閉"));
    const generation = this.generation;
    const task = this.queue.then(() => {
      if (generation !== this.generation || this.disposed) return;
      if (this.error) throw this.error;
      return operation(generation);
    });
    this.queue = task.catch(() => {});
    return task;
  }

  waitUntil(predicate, generation) {
    return new Promise((resolve, reject) => {
      let timer;
      let done = false;
      const check = () => {
        if (done) return;
        clearTimeout(timer);
        if (
          this.error ||
          generation !== this.generation ||
          this.disposed ||
          predicate()
        ) {
          done = true;
          this.waiters.delete(check);
          this.error ? reject(this.error) : resolve();
        } else timer = setTimeout(check, 20);
      };
      this.waiters.add(check);
      check();
    });
  }

  appendPcm(pcm) {
    if (!(pcm instanceof Int16Array))
      return Promise.reject(new TypeError("PCM 必須是 Int16Array"));
    if (!pcm.length)
      return this.disposed
        ? Promise.reject(new Error("人物引擎已關閉"))
        : Promise.resolve();
    const copy = pcm.slice();
    return this.serial(async (generation) => {
      await this.prepare();
      if (generation !== this.generation) return;
      if (!this.handle || this.handle.closed || this.handle.stopped) {
        this.handle = this.controller.beginStream({
          utteranceId: `audio-${generation}-${performance.now()}`,
        });
        this.sequence = this.sample = 0;
      }
      for (let offset = 0; offset < copy.length; offset += 640) {
        if (generation !== this.generation) return;
        const samples = copy.slice(offset, offset + 640);
        const result = this.controller.appendPcm(this.handle, {
          sequence: this.sequence,
          startSample: this.sample,
          samples,
        });
        if (result.accepted === false || result.status === "rejected")
          throw new Error(result.reason || "人物音訊遭拒絕");
        this.sequence++;
        this.sample += samples.length;
        if (result.status === "backpressure") {
          await this.waitUntil(
            () =>
              this.controller.audioQueue.reduce(
                (n, chunk) => n + chunk.duration,
                0,
              ) < 1.5,
            generation,
          );
        }
      }
    });
  }

  finishAudio() {
    return this.serial(async (generation) => {
      if (!this.handle || this.handle.stopped) return;
      const result = this.controller.endStream(this.handle);
      if (result.status === "rejected") throw new Error(result.reason);
      await this.waitUntil(() => this.controller.state === "ready", generation);
    });
  }

  stop() {
    this.generation++;
    this.queue = Promise.resolve();
    if (this.handle) this.controller.stop(this.handle);
    this.handle = null;
    if (this.player) {
      this.player.releaseControls();
      this.player.draw();
    }
    for (const notify of [...this.waiters]) notify();
  }

  diagnostics() {
    return {
      state: this.state,
      generation: this.generation,
      speaking: this.speaking,
      controls: Array.from(this.player?.controls || []),
      sources: this.controller.liveSources.size,
      telemetry: { ...this.controller.telemetry },
      frame: this.player?.videoFrame ?? -1,
    };
  }

  dispose() {
    if (this.disposed) return;
    this.stop();
    this.disposed = true;
    this.loadGeneration++;
    this.loadAbort?.abort();
    for (const cancel of [...this.videoWaiters]) cancel();
    this.controller.dispose();
    this.player?.dispose();
    this.video.pause();
    this.output.disconnect();
    void this.audioContext.close();
    if (this.workerBootstrap) URL.revokeObjectURL(this.workerBootstrap);
    this.listeners.clear();
  }
}
