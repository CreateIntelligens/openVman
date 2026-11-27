import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const bundleUrl = new URL("../dist/openvman-avatar-sdk.js", import.meta.url);

export function memoryStorage() {
  const values = new Map();
  return {
    getItem: (key) => (values.has(key) ? values.get(key) : null),
    setItem: (key, value) => values.set(key, String(value)),
  };
}

export async function loadSdk({
  audioState = "running",
  cacheStorage,
  fetchHook,
  autoEnd = true,
  characterStatus: initialCharacterStatus = 200,
  charactersBody = { characters: [{ char_id: "000", label: "Default" }] },
  charactersStatus = 200,
  deferDecode = false,
  deferVideoReady = false,
  resumeSucceeds = true,
  videoLoadSucceeds = true,
  videoLoadResult,
  videoPlayBlocked = false,
  videoPlaySucceeds = true,
  localStorage = memoryStorage(),
  timers = { setTimeout, clearTimeout, setInterval() { return 0; }, clearInterval() {} },
} = {}) {
  let characterStatus = initialCharacterStatus;
  const source = await readFile(bundleUrl, "utf8");
  const script = { src: "https://avatar.example/static/sdk/openvman-avatar-sdk.js" };
  const elements = new Map();
  const requests = [];
  const runtimeCalls = {
    canvasCalls: [],
    clearAudio: 0,
    pushedAudio: 0,
    audioContexts: 0,
    audioCloses: 0,
    resumeCalled: 0,
    scheduledStarts: [],
    sourceStarted: 0,
    sourceStopped: 0,
    videoPlays: 0,
    videoRemoved: 0,
    videoSources: [],
  };
  let playBlocked = videoPlayBlocked;
  const windowListeners = new Map();
  let finishDecode;
  let finishVideoReady;
  let renderingTime = 0;
  let context;
  let audioContext;
  const documentEvents = new EventTarget();
  const createElement = (tagName) => {
    const canvasContext = {
      globalAlpha: 1,
      clearRect(_x, _y, width, height) {
        runtimeCalls.canvasCalls.push(`clearRect ${width}x${height}`);
      },
      drawImage(...args) {
        runtimeCalls.canvasCalls.push(
          `drawImage ${args.length} alpha=${canvasContext.globalAlpha}`,
        );
      },
    };
    const listeners = new Map();
    const element = {
      children: [],
      className: "",
      dataset: {},
      parent: null,
      addEventListener(type, handler) {
        const handlers = listeners.get(type) ?? new Set();
        handlers.add(handler);
        listeners.set(type, handlers);
      },
      removeEventListener(type, handler) {
        listeners.get(type)?.delete(handler);
      },
      dispatchEvent(event) {
        for (const handler of listeners.get(event.type) ?? []) handler(event);
        return !event.defaultPrevented;
      },
      style: { setProperty() {} },
      append(...children) {
        for (const child of children) {
          child.parent = this;
          this.children.push(child);
          if (child.tagName === "script") {
            const videoListeners = new Map();
            context.window.characterVideo = {
              addEventListener(type, handler) {
                const handlers = videoListeners.get(type) ?? new Set();
                handlers.add(handler);
                videoListeners.set(type, handlers);
              },
              error: null,
              currentTime: 0,
              paused: true,
              load() {
                runtimeCalls.videoSources.push(this.src);
                const succeeds = videoLoadResult
                  ? videoLoadResult(this.src, runtimeCalls.videoSources.length - 1)
                  : videoLoadSucceeds;
                this.readyState = 0;
                const finish = () => {
                  const type = succeeds ? "canplay" : "error";
                  if (succeeds) this.readyState = 3;
                  for (const handler of videoListeners.get(type) ?? []) {
                    handler();
                  }
                };
                if (deferVideoReady) {
                  finishVideoReady = finish;
                } else {
                  queueMicrotask(finish);
                }
              },
              async play() {
                if (playBlocked) {
                  const error = new Error("The request is not allowed by the user agent");
                  error.name = "NotAllowedError";
                  throw error;
                }
                if (!videoPlaySucceeds) {
                  throw new Error("playback rejected");
                }
                runtimeCalls.videoPlays += 1;
                this.paused = false;
              },
              pause() {
                this.paused = true;
                for (const handler of videoListeners.get("pause") ?? []) handler();
              },
              readyState: 0,
              remove() {
                runtimeCalls.videoRemoved += 1;
              },
              removeEventListener(type, handler) {
                videoListeners.get(type)?.delete(handler);
              },
            };
            context.window.createQtAppInstance = async () => ({
              HEAPU8: new Uint8Array(16384),
              _clearAudio() {
                runtimeCalls.clearAudio += 1;
              },
              _free() {},
              _malloc: () => 0,
              _processSecret() {},
              _setAudioBuffer() {
                runtimeCalls.pushedAudio += 1;
              },
              stringToUTF8() {},
            });
            queueMicrotask(() => child.onload());
          }
        }
      },
      remove() {
        for (const child of [...this.children]) child.remove();
        if (this.id) elements.delete(this.id);
        if (this.parent) {
          this.parent.children = this.parent.children.filter(
            (child) => child !== this,
          );
        }
      },
      tagName,
    };
    if (tagName === "canvas") {
      element.getContext = () => canvasContext;
    }
    Object.defineProperty(element, "id", {
      get() {
        return this._id ?? "";
      },
      set(value) {
        this._id = value;
        elements.set(value, this);
      },
    });
    return element;
  };
  const body = createElement("body");
  const head = createElement("head");
  context = {
    AbortController,
    HTMLMediaElement: { HAVE_CURRENT_DATA: 2 },
    TextDecoder,
    TextEncoder,
    Blob,
    URL,
    Uint8Array,
    console,
    document: {
      addEventListener: documentEvents.addEventListener.bind(documentEvents),
      body,
      currentScript: script,
      createElement,
      dispatchEvent: documentEvents.dispatchEvent.bind(documentEvents),
      getElementById: (id) => elements.get(id) ?? null,
      head,
      removeEventListener: documentEvents.removeEventListener.bind(documentEvents),
      visibilityState: "visible",
    },
    fetch: async (url, options) => {
      requests.push({
        options,
        resumeCalled: runtimeCalls.resumeCalled,
        url,
      });
      const hooked = await fetchHook?.(url, options);
      if (hooked !== undefined) return hooked;
      if (url.endsWith("/characters")) {
        return {
          json: async () => charactersBody,
          ok: charactersStatus === 200,
          status: charactersStatus,
        };
      }
      const isCharacter = url.includes("combined_data.json.gz");
      return {
        arrayBuffer: async () => new TextEncoder().encode("{}").buffer,
        blob: async () => new Blob([new TextEncoder().encode("{}")]),
        ok: !isCharacter || characterStatus === 200,
        status: isCharacter ? characterStatus : 200,
      };
    },
    Response,
    ...(cacheStorage ? { caches: cacheStorage } : {}),
    queueMicrotask,
    performance: {
      now: () => renderingTime,
    },
    window: {
      ...timers,
      addEventListener(type, handler) {
        const handlers = windowListeners.get(type) ?? new Set();
        handlers.add(handler);
        windowListeners.set(type, handlers);
      },
      localStorage,
      removeEventListener(type, handler) {
        windowListeners.get(type)?.delete(handler);
      },
    },
  };
  context.window.AudioContext = class {
    constructor() {
      runtimeCalls.audioContexts += 1;
      audioContext = this;
      this.currentTime = 0;
      this.destination = {};
      this.state = audioState;
    }
    async close() { runtimeCalls.audioCloses += 1; }
    createBuffer(_channels, length, sampleRate) {
      return {
        copyToChannel() {},
        getChannelData: () => new Float32Array(length),
        length,
        numberOfChannels: 1,
        sampleRate,
      };
    }
    createBufferSource() {
      const source = {
        connect() {},
        onended: null,
        start(when = 0) {
          runtimeCalls.sourceStarted += 1;
          runtimeCalls.scheduledStarts.push(when);
          if (autoEnd) queueMicrotask(() => source.onended?.());
        },
        stop() {
          runtimeCalls.sourceStopped += 1;
        },
      };
      return source;
    }
    async decodeAudioData() {
      const buffer = {
        getChannelData: () => new Float32Array([0, 0.5, -0.5, 0]),
        length: 4,
        numberOfChannels: 1,
        sampleRate: 16000,
      };
      if (!deferDecode) return buffer;
      return new Promise((resolve) => {
        finishDecode = () => resolve(buffer);
      });
    }
    async resume() {
      runtimeCalls.resumeCalled += 1;
      if (resumeSucceeds) this.state = "running";
    }
  };
  context.globalThis = context;
  vm.runInNewContext(source, context);
  return {
    document: context.document,
    finishDecode: () => finishDecode?.(),
    finishVideoReady: () => finishVideoReady?.(),
    /** A tap or key press on the page; the browser lets playback start from here on. */
    gesture(type = "touchend") {
      playBlocked = false;
      for (const handler of [...(windowListeners.get(type) ?? [])]) handler({ type });
    },
    gestureListeners: () => [...windowListeners.values()].reduce((sum, set) => sum + set.size, 0),
    requests,
    runtimeCalls,
    sdk: context.window.OpenVmanAvatar,
    video: () => context.window.characterVideo,
    setAudioTime(value) {
      audioContext.currentTime = value;
    },
    setCharacterStatus(value) {
      characterStatus = value;
    },
    setRenderingTime(value) {
      renderingTime = value;
    },
  };
}

test("exposes the framework-free OpenVmanAvatar global", async () => {
  const { sdk } = await loadSdk();

  assert.equal(typeof sdk?.init, "function");
});

test("initializes without an API key", async () => {
  const { sdk } = await loadSdk();

  const avatar = await sdk.init({ characterId: "000" });

  assert.equal(typeof avatar.playAudio, "function");
  assert.equal(typeof avatar.pushPcm, "function");
  assert.equal(typeof avatar.rebuildAudio, "function");
  assert.equal("speak" in avatar, false);
  assert.equal("setPersona" in avatar, false);
});

function watchdogTimers(t) {
  t.mock.timers.enable({ apis: ["setTimeout", "setInterval"] });
  return { setTimeout, clearTimeout, setInterval, clearInterval };
}

test("reports AUDIO_STALLED after a single resume and rebuilds inside the calling gesture", async (t) => {
  const timers = watchdogTimers(t);
  const h = await loadSdk({ autoEnd: false, timers });
  const avatar = await h.sdk.init({ audioLeadMs: 0 });
  t.after(() => avatar.destroy());
  const errors = [];
  avatar.on("error", (error) => errors.push(error));
  await avatar.pushPcm(new Int16Array([1, 2, 3]));

  t.mock.timers.tick(1500);
  t.mock.timers.tick(400);
  assert.equal(h.runtimeCalls.resumeCalled, 1);
  assert.equal(errors.length, 0);
  await new Promise(setImmediate);
  t.mock.timers.tick(600);
  assert.equal(errors.length, 1);
  assert.equal(errors[0].code, "AUDIO_STALLED");
  assert.equal(errors[0].recoverable, true);

  h.setAudioTime(5);
  const rebuilt = avatar.rebuildAudio();
  assert.equal(h.runtimeCalls.audioContexts, 2);
  assert.equal(h.runtimeCalls.audioCloses, 1);
  assert.equal(h.runtimeCalls.resumeCalled, 2);
  assert.equal(h.runtimeCalls.sourceStopped, 1);
  await rebuilt;

  await avatar.pushPcm(new Int16Array([1, 2]));
  assert.equal(h.runtimeCalls.scheduledStarts.at(-1), 0);
  t.mock.timers.tick(1500);
  h.setAudioTime(1);
  t.mock.timers.tick(400);
  assert.equal(errors.length, 1);
  assert.equal(h.runtimeCalls.resumeCalled, 2);
});

test("replays a visible pause and reports VIDEO_STALLED once per stationary period", async (t) => {
  const timers = watchdogTimers(t);
  const h = await loadSdk({ timers });
  const avatar = await h.sdk.init({});
  t.after(() => avatar.destroy());
  const errors = [];
  avatar.on("error", (error) => errors.push(error));
  const video = h.video();
  h.document.visibilityState = "hidden";
  h.document.dispatchEvent(new Event("visibilitychange"));
  video.pause();
  assert.equal(h.runtimeCalls.videoPlays, 1);
  h.setRenderingTime(5000);
  t.mock.timers.tick(500);
  assert.equal(errors.length, 0);
  h.document.visibilityState = "visible";
  h.document.dispatchEvent(new Event("visibilitychange"));
  assert.equal(h.runtimeCalls.videoPlays, 2);

  h.setRenderingTime(6500);
  t.mock.timers.tick(1500);
  assert.equal(errors.length, 0);
  h.setRenderingTime(7000);
  t.mock.timers.tick(500);
  assert.equal(errors.length, 1);
  assert.equal(errors[0].code, "VIDEO_STALLED");
  assert.equal(errors[0].paused, false);
  assert.equal(errors[0].readyState, 3);
  h.setRenderingTime(9000);
  t.mock.timers.tick(2000);
  assert.equal(errors.length, 1);

  avatar.destroy();
  video.pause();
  assert.equal(h.runtimeCalls.videoPlays, 2);
});

test("the video watchdog leaves first playback to the SDK gesture handler", async (t) => {
  const timers = watchdogTimers(t);
  const h = await loadSdk({ videoPlayBlocked: true, timers });
  const avatar = await h.sdk.init({});
  t.after(() => avatar.destroy());
  const errors = [];
  avatar.on("error", (error) => errors.push(error.code));
  await Promise.resolve();
  h.setRenderingTime(4000);
  t.mock.timers.tick(4000);
  assert.equal(avatar.videoAwaitingGesture, true);
  assert.deepEqual(errors, ["AUTOPLAY_BLOCKED"]);
  assert.equal(h.runtimeCalls.videoPlays, 0);
  h.gesture();
  await Promise.resolve();
  assert.equal(avatar.videoAwaitingGesture, false);
  assert.equal(h.runtimeCalls.videoPlays, 1);
  h.setRenderingTime(4500);
  t.mock.timers.tick(500);
  assert.deepEqual(errors, ["AUTOPLAY_BLOCKED"]);
});

test("derives resources from the SDK script origin", async () => {
  const { sdk } = await loadSdk();

  assert.equal(sdk.resourceBaseUrl, "https://avatar.example");
});

test("loads character files from the /static family", async () => {
  const { requests, sdk } = await loadSdk();

  await sdk.init({ characterId: "000" });

  assert.ok(
    requests.some(
      ({ url }) =>
        url === "https://avatar.example/static/characters/000/combined_data.json.gz",
    ),
  );
  assert.equal(
    requests.some(({ url }) => String(url).includes("/assets/")),
    false,
  );
});

test("reuses identical init and rejects different page-lifetime init", async () => {
  const { sdk } = await loadSdk();
  const first = await sdk.init({ characterId: "000" });

  assert.equal(await sdk.init({ characterId: "000" }), first);
  await assert.rejects(
    sdk.init({ characterId: "other" }),
    (error) => error.code === "INSTANCE_EXISTS",
  );
});

test("creates direct DOM, cleans it on destroy, and forbids runtime reuse", async () => {
  const { document, runtimeCalls, sdk } = await loadSdk();
  const avatar = await sdk.init({ characterId: "000" });

  assert.ok(document.getElementById("canvas_video"));
  assert.ok(document.getElementById("canvas_gl"));
  assert.ok(document.getElementById("screen"));
  avatar.destroy();
  assert.equal(document.getElementById("canvas_video"), null);
  assert.equal(runtimeCalls.videoRemoved, 1);
  await assert.rejects(
    sdk.init({ characterId: "000" }),
    (error) => error.code === "RUNTIME_DISPOSED",
  );
});

test("rejects vendor DOM ID conflicts without overwriting the host", async () => {
  const { document, sdk } = await loadSdk();
  const existing = document.createElement("canvas");
  existing.id = "canvas_video";

  await assert.rejects(
    sdk.init({ characterId: "000" }),
    (error) => error.code === "DOM_CONFLICT",
  );
  assert.equal(document.getElementById("canvas_video"), existing);
});

test("playAudio decodes host audio without calling an embed API", async () => {
  const { requests, runtimeCalls, sdk } = await loadSdk();
  const avatar = await sdk.init({ audioLeadMs: 0, characterId: "000" });
  const states = [];
  avatar.on("speaking", (event) => states.push(event.state));

  await avatar.playAudio(new ArrayBuffer(16));

  assert.equal(requests.some(({ url }) => url.includes("/api/embed/")), false);
  assert.ok(runtimeCalls.pushedAudio > 0);
  assert.deepEqual(states, ["start", "stop"]);
});

test("playAudio reports autoplay blocking with a named error event", async () => {
  const { sdk } = await loadSdk({
    audioState: "suspended",
    resumeSucceeds: false,
  });
  const avatar = await sdk.init({ characterId: "000" });
  const errors = [];
  avatar.on("error", (event) => errors.push(event.code));

  await assert.rejects(
    avatar.playAudio(new ArrayBuffer(16)),
    (error) => error.code === "AUTOPLAY_BLOCKED",
  );
  assert.deepEqual(errors, ["AUTOPLAY_BLOCKED"]);
});

test("interrupt stops pending speech and clears the runtime", async () => {
  const { runtimeCalls, sdk } = await loadSdk({ autoEnd: false });
  const avatar = await sdk.init({ characterId: "000" });
  const states = [];
  avatar.on("speaking", (event) => states.push(event.state));
  const playback = avatar.playAudio(new ArrayBuffer(16));
  await new Promise((resolve) => setImmediate(resolve));

  avatar.interrupt();
  await Promise.race([
    playback,
    new Promise((_, reject) => setTimeout(
      () => reject(new Error("interrupted playback did not settle")),
      20,
    )),
  ]);

  assert.deepEqual(states, ["start", "stop"]);
  assert.ok(runtimeCalls.clearAudio > 0);
});

test("playAudio resumes the audio context before decoding", async () => {
  const { runtimeCalls, sdk } = await loadSdk({
    audioState: "suspended",
  });
  const avatar = await sdk.init({ characterId: "000" });

  await avatar.playAudio(new ArrayBuffer(16));

  assert.equal(runtimeCalls.resumeCalled, 1);
});

test("interrupt during decode prevents PCM and source playback", async () => {
  const { finishDecode, runtimeCalls, sdk } = await loadSdk({
    deferDecode: true,
  });
  const avatar = await sdk.init({ characterId: "000" });
  const playback = avatar.playAudio(new ArrayBuffer(16));
  await new Promise((resolve) => setImmediate(resolve));

  avatar.interrupt();
  finishDecode();
  await playback;

  assert.equal(runtimeCalls.pushedAudio, 0);
  assert.equal(runtimeCalls.sourceStarted, 0);
});

test("different container is treated as a different init", async () => {
  const { document, sdk } = await loadSdk();
  const firstContainer = document.createElement("section");
  const secondContainer = document.createElement("section");
  await sdk.init({
    container: firstContainer,
  });

  await assert.rejects(
    sdk.init({
      container: secondContainer,
    }),
    (error) => error.code === "INSTANCE_EXISTS",
  );
});

test("a failed character download leaves nothing behind and init can run again", async () => {
  const { document, sdk, setCharacterStatus } = await loadSdk({ characterStatus: 404 });

  await assert.rejects(
    sdk.init({ characterId: "000" }),
    (error) => error.code === "RESOURCE_LOAD_FAILED",
  );
  assert.equal(document.getElementById("canvas_video"), null);

  setCharacterStatus(200);
  const avatar = await sdk.init({ characterId: "000" });
  assert.equal(typeof avatar.playAudio, "function");
});

test("does not resolve init before the character video can render", async () => {
  const { finishVideoReady, sdk } = await loadSdk({
    deferVideoReady: true,
  });
  let initialized = false;
  const initialization = sdk.init({ characterId: "000" }).then(() => {
    initialized = true;
  });
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(initialized, false);
  finishVideoReady();
  await initialization;
  assert.equal(initialized, true);
});

test("rejects init when the character video fails to load", async () => {
  const { sdk } = await loadSdk({
    videoLoadSucceeds: false,
  });

  await assert.rejects(
    sdk.init({ characterId: "000" }),
    (error) => error.code === "RESOURCE_LOAD_FAILED",
  );
});

test("rejects init when the character video cannot start", async () => {
  const { sdk } = await loadSdk({
    videoPlaySucceeds: false,
  });

  await assert.rejects(
    sdk.init({ characterId: "000" }),
    (error) => error.code === "RESOURCE_LOAD_FAILED",
  );
});

test("pushPcm queues host chunks in order without backend requests", async () => {
  const { requests, runtimeCalls, sdk } = await loadSdk({ autoEnd: false });
  const avatar = await sdk.init({ audioLeadMs: 0, characterId: "000" });

  await avatar.pushPcm(new Int16Array(1600));
  await avatar.pushPcm(new Int16Array(800));

  assert.equal(requests.some(({ url }) => url.includes("/api/embed/")), false);
  assert.equal(runtimeCalls.pushedAudio, 2);
  assert.deepEqual(runtimeCalls.scheduledStarts, [0, 0.1]);
});

test("idle rendering keeps the native frame until PCM playback begins", async () => {
  const { document, runtimeCalls, sdk, setRenderingTime } = await loadSdk({
    autoEnd: false,
  });
  const avatar = await sdk.init({ audioLeadMs: 0, characterId: "000" });
  const canvas = document.getElementById("canvas_video");
  const context = canvas.getContext("2d");
  canvas.width = 1080;
  canvas.height = 1920;
  const renderFrame = () => {
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.drawImage({}, 0, 0, canvas.width, canvas.height);
    context.clearRect(452, 486, 232, 232);
    context.drawImage({}, 0, 0, 180, 180, 452, 486, 232, 232);
  };

  renderFrame();
  assert.deepEqual(runtimeCalls.canvasCalls, [
    "clearRect 1080x1920",
    "drawImage 5 alpha=1",
  ]);

  runtimeCalls.canvasCalls.length = 0;
  await avatar.pushPcm(new Int16Array(1600));
  setRenderingTime(100);
  renderFrame();
  assert.deepEqual(runtimeCalls.canvasCalls, [
    "clearRect 1080x1920",
    "drawImage 5 alpha=1",
    "drawImage 9 alpha=0.5",
  ]);

  runtimeCalls.canvasCalls.length = 0;
  avatar.interrupt();
  renderFrame();
  assert.deepEqual(runtimeCalls.canvasCalls, [
    "clearRect 1080x1920",
    "drawImage 5 alpha=1",
  ]);
});

test("a new playAudio call replaces current playback", async () => {
  const { runtimeCalls, sdk } = await loadSdk({ autoEnd: false });
  const avatar = await sdk.init({ characterId: "000" });
  const first = avatar.playAudio(new ArrayBuffer(16));
  await new Promise((resolve) => setImmediate(resolve));

  const second = avatar.playAudio(new ArrayBuffer(16));
  await new Promise((resolve) => setImmediate(resolve));

  assert.ok(runtimeCalls.sourceStopped > 0);
  avatar.interrupt();
  await Promise.all([first, second]);
});

test("listCharacters fetches the public character list from the SDK origin", async () => {
  const { requests, sdk } = await loadSdk({
    charactersBody: {
      characters: [
        { char_id: "000", label: "Default" },
        { char_id: "0713", label: "夏季限定" },
      ],
    },
  });

  const characters = await sdk.listCharacters();

  assert.equal(characters.length, 2);
  assert.equal(characters[0].charId, "000");
  assert.equal(characters[0].label, "Default");
  assert.equal(characters[1].charId, "0713");
  assert.equal(characters[1].label, "夏季限定");
  assert.ok(
    requests.some(({ url }) => url === "https://avatar.example/api/v1/characters"),
  );
});

test("listCharacters reports a named error when the request fails", async () => {
  const { sdk } = await loadSdk({ charactersStatus: 500 });

  await assert.rejects(
    sdk.listCharacters(),
    (error) => error.code === "RESOURCE_LOAD_FAILED",
  );
});

test("supports a silent audio output for host-driven playback", async () => {
  const typesSource = await readFile(new URL("../src/types.ts", import.meta.url), "utf8");
  const audioSource = await readFile(new URL("../src/audio.ts", import.meta.url), "utf8");
  const mainSource = await readFile(new URL("../src/main.ts", import.meta.url), "utf8");

  assert.match(typesSource, /audioOutput\?: OpenVmanAvatarAudioOutput/);
  assert.match(typesSource, /"speaker" \| "silent"/);
  assert.match(audioSource, /audioOutput === "silent" \? new ClockPlayer\(\)/);
  assert.match(mainSource, /audioOutput: options\.audioOutput \?\? "speaker"/);
});

test("a lost WebGL lip-sync canvas reports an error and keeps the avatar alive", async () => {
  const { document, sdk } = await loadSdk();
  const avatar = await sdk.init({ characterId: "000" });
  const errors = [];
  avatar.on("error", (event) => errors.push(event.code));
  const event = { defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, type: "webglcontextlost" };

  document.getElementById("canvas_gl").dispatchEvent(event);

  assert.deepEqual(errors, ["WEBGL_CONTEXT_LOST"]);
  // 不 preventDefault 的話，瀏覽器不會再給這個畫布 context。
  assert.equal(event.defaultPrevented, true);
  avatar.destroy();
});

function fakeCaches() {
  const store = new Map();
  const cache = {
    async match(key) {
      const response = store.get(String(key));
      return response ? response.clone() : undefined;
    },
    async put(key, response) {
      store.set(String(key), response);
    },
    async delete(key) {
      return store.delete(String(key));
    },
  };
  return {
    storage: {
      open: async () => cache,
      delete: async () => {
        const had = store.size > 0;
        store.clear();
        return had;
      },
    },
    store,
  };
}

function assetResponse({ status = 200, lastModified = "", onBodyRead } = {}) {
  const headers = new Map([
    ["content-length", "2"],
    ["last-modified", lastModified],
  ]);
  return {
    arrayBuffer: async () => new TextEncoder().encode("{}").buffer,
    blob: async () => {
      onBodyRead?.();
      return new Blob([new TextEncoder().encode("{}")]);
    },
    headers: { get: (name) => headers.get(name.toLowerCase()) ?? null },
    ok: status >= 200 && status < 300,
    status,
  };
}

const isAsset = (url) => String(url).includes("/static/");
const settle = () => new Promise((resolve) => setTimeout(resolve, 20));
const storedKeys = (store, fragment) => [...store.keys()].filter((key) => key.includes(fragment));

test("starts from the browser's copy when the server is unreachable", async () => {
  const { storage, store } = fakeCaches();
  const first = await loadSdk({ cacheStorage: storage });
  assert.equal((await first.sdk.init({ characterId: "000" })).assetsFromCache, false);
  await settle();
  assert.equal(storedKeys(store, "openvman-avatar.cache/manifest").length, 2);

  const offline = await loadSdk({
    cacheStorage: storage,
    fetchHook: (url) => {
      if (isAsset(url)) throw new TypeError("Failed to fetch");
    },
  });
  const avatar = await offline.sdk.init({ characterId: "000" });
  await settle();
  assert.equal(avatar.assetsFromCache, true);
  // 背景檢查連不上只代表暫時斷線，存著的檔案要留著。
  assert.equal(storedKeys(store, "openvman-avatar.cache/manifest").length, 2);
});

test("a refused character is not shown from the stored copy and is dropped", async () => {
  const { storage, store } = fakeCaches();
  await (await loadSdk({ cacheStorage: storage })).sdk.init({ characterId: "000" });
  await settle();

  const revoked = await loadSdk({
    cacheStorage: storage,
    fetchHook: (url) => (String(url).includes("/characters/") ? assetResponse({ status: 403 }) : undefined),
  });
  await assert.rejects(
    revoked.sdk.init({ characterId: "000" }),
    (error) => error.code === "RESOURCE_LOAD_FAILED",
  );
  assert.equal(revoked.document.getElementById("canvas_video"), null);
  assert.deepEqual(storedKeys(store, "/characters/"), []);
  assert.equal(storedKeys(store, "/runtime/").length, 2);
});

test("a page served instead of the file never replaces the stored copy", async () => {
  const { storage, store } = fakeCaches();
  const stamp = "Mon, 23 Nov 2026 03:00:00 GMT";
  await (await loadSdk({
    cacheStorage: storage,
    fetchHook: (url) => (isAsset(url) ? assetResponse({ lastModified: stamp }) : undefined),
  })).sdk.init({ characterId: "000" });
  await settle();
  const before = [...store.keys()].sort();

  const portal = await loadSdk({
    cacheStorage: storage,
    fetchHook: (url) => {
      if (!isAsset(url)) return undefined;
      const page = assetResponse({ lastModified: "Tue, 24 Nov 2026 00:00:00 GMT" });
      const get = page.headers.get;
      page.headers = { get: (name) => (name.toLowerCase() === "content-type" ? "text/html; charset=utf-8" : get(name)) };
      return page;
    },
  });
  assert.equal((await portal.sdk.init({ characterId: "000" })).assetsFromCache, true);
  await settle();
  assert.deepEqual([...store.keys()].sort(), before);
});

test("a download cut off midway is retried", async () => {
  let cut = 0;
  const { sdk } = await loadSdk({
    fetchHook: (url) => {
      if (!String(url).endsWith("01.webm") || cut > 0) return undefined;
      cut += 1;
      const response = assetResponse();
      response.blob = async () => { throw new TypeError("network error"); };
      return response;
    },
  });
  assert.equal(typeof (await sdk.init({ characterId: "000" })).ask, "function");
  assert.equal(cut, 1);
});

test("a server that never answers does not keep a stored avatar from showing", async () => {
  const { storage } = fakeCaches();
  await (await loadSdk({ cacheStorage: storage })).sdk.init({ characterId: "000" });
  await settle();

  const hung = await loadSdk({
    cacheStorage: storage,
    fetchHook: (url, options) => (isAsset(url)
      ? new Promise((_resolve, reject) => options.signal.addEventListener("abort", () => reject(new Error("aborted"))))
      : undefined),
  });
  const started = Date.now();
  assert.equal((await hung.sdk.init({ characterId: "000" })).assetsFromCache, true);
  assert.ok(Date.now() - started < 6000);
});

test("an unchanged file stops downloading once its headers match", async () => {
  const { storage } = fakeCaches();
  const stamp = "Mon, 23 Nov 2026 03:00:00 GMT";
  await (await loadSdk({
    cacheStorage: storage,
    fetchHook: (url) => (isAsset(url) ? assetResponse({ lastModified: stamp }) : undefined),
  })).sdk.init({ characterId: "000" });
  await settle();

  let bodiesRead = 0;
  const signals = [];
  const again = await loadSdk({
    cacheStorage: storage,
    fetchHook: (url, options) => {
      if (!isAsset(url)) return undefined;
      signals.push(options?.signal);
      return assetResponse({ lastModified: stamp, onBodyRead: () => { bodiesRead += 1; } });
    },
  });
  assert.equal((await again.sdk.init({ characterId: "000" })).assetsFromCache, true);
  await settle();
  assert.equal(signals.length, 4);
  assert.ok(signals.every((signal) => signal?.aborted));
  assert.ok(again.requests.filter(({ url }) => isAsset(url)).every(({ options }) => options?.cache === "no-cache"));
  assert.equal(bodiesRead, 0);
});

test("retries a dropped connection before giving up", async () => {
  let failures = 0;
  const { sdk } = await loadSdk({
    fetchHook: (url) => {
      if (String(url).endsWith("combined_data.json.gz") && failures === 0) {
        failures += 1;
        throw new TypeError("Failed to fetch");
      }
    },
  });
  const avatar = await sdk.init({ characterId: "000" });
  assert.equal(failures, 1);
  assert.equal(typeof avatar.ask, "function");
});

test("cacheAssets false never touches Cache Storage", async () => {
  const { storage, store } = fakeCaches();
  const { sdk } = await loadSdk({ cacheStorage: storage });
  await sdk.init({ cacheAssets: false, characterId: "000" });
  await settle();
  assert.equal(store.size, 0);
});

test("a video the browser will not start waits for a tap instead of failing init", async () => {
  const { gesture, gestureListeners, runtimeCalls, sdk } = await loadSdk({ videoPlayBlocked: true });
  const avatar = await sdk.init({ characterId: "000" });
  assert.equal(avatar.videoAwaitingGesture, true);

  const errors = [];
  avatar.on("error", (event) => errors.push(event.code));
  await new Promise((resolve) => setImmediate(resolve));
  // 頁面晚一步才訂閱 error 也要知道該請使用者點一下。
  assert.deepEqual(errors, ["AUTOPLAY_BLOCKED"]);

  gesture("touchend");
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(runtimeCalls.videoPlays, 1);
  assert.equal(avatar.videoAwaitingGesture, false);
  assert.equal(gestureListeners(), 0);
});

test("other video start failures still reject init", async () => {
  const { sdk } = await loadSdk({ videoPlaySucceeds: false });
  await assert.rejects(sdk.init({ characterId: "000" }), (error) => error.code === "RESOURCE_LOAD_FAILED");
});

test("a stored video that will not play is dropped and downloaded again", async () => {
  const { storage, store } = fakeCaches();
  await (await loadSdk({ cacheStorage: storage })).sdk.init({ characterId: "000" });
  await settle();
  assert.equal(storedKeys(store, "/characters/").length, 2);

  // 第二次開頁：從瀏覽器拿出的那份播不了（iOS 的情形），重新下載的那份可以。
  const second = await loadSdk({
    cacheStorage: storage,
    videoLoadResult: (_src, nth) => nth > 0,
  });
  const avatar = await second.sdk.init({ characterId: "000" });
  await settle();
  assert.equal(avatar.assetsFromCache, true);
  assert.equal(second.runtimeCalls.videoSources.length, 2);
  assert.ok(second.runtimeCalls.videoSources.every((src) => src.startsWith("blob:")));
  assert.ok(
    second.requests.some(({ url, options }) => String(url).endsWith("/01.webm") && !options?.headers?.["If-None-Match"]),
    "the video is downloaded again",
  );
  assert.deepEqual(storedKeys(store, "/characters/"), [], "the unplayable stored copy is gone");
});

test("a freshly downloaded video that will not play falls back to its URL without a second download", async () => {
  const { requests, runtimeCalls, sdk } = await loadSdk({
    videoLoadResult: (src) => !src.startsWith("blob:"),
  });
  await sdk.init({ characterId: "000" });
  assert.equal(runtimeCalls.videoSources.length, 2);
  assert.match(runtimeCalls.videoSources[1], /\/01\.webm$/);
  assert.equal(requests.filter(({ url }) => String(url).endsWith("/01.webm")).length, 1);
});

test("clearAssetCache removes every stored file", async () => {
  const { storage, store } = fakeCaches();
  const { sdk } = await loadSdk({ cacheStorage: storage });
  await sdk.init({ characterId: "000" });
  await settle();
  assert.ok(store.size > 0);
  assert.equal(await sdk.clearAssetCache(), true);
  assert.equal(store.size, 0);
  assert.equal(await (await loadSdk()).sdk.clearAssetCache(), false, "no Cache Storage resolves false");
});

test("a page that forbids blob: video keeps its stored copy and stops downloading the video twice", async () => {
  const { storage, store } = fakeCaches();
  const localStorage = memoryStorage();
  const blobBlocked = (src) => !src.startsWith("blob:");
  const videoDownloads = (requests) => requests.filter(
    ({ url, options }) => String(url).endsWith("/01.webm") && options?.method !== "HEAD",
  ).length;
  const visits = [];
  for (let visit = 0; visit < 4; visit += 1) {
    const page = await loadSdk({ cacheStorage: storage, localStorage, videoLoadResult: blobBlocked });
    const avatar = await page.sdk.init({ characterId: "000" });
    await settle();
    visits.push({
      fromCache: avatar.assetsFromCache,
      sources: page.runtimeCalls.videoSources.map((src) => (src.startsWith("blob:") ? "blob" : "url")),
      stored: storedKeys(store, "/characters/").length,
      downloads: videoDownloads(page.requests),
    });
  }
  // 存檔一直留著；第二次開頁發現新下載的也播不了之後就記住，之後不再多下載一次。
  assert.deepEqual(visits.map((v) => v.stored), [2, 2, 2, 2]);
  assert.deepEqual(visits.map((v) => v.fromCache), [false, true, true, true]);
  assert.deepEqual(visits[1].sources, ["blob", "blob", "url"]);
  assert.deepEqual(visits[2].sources, ["blob", "url"]);
  assert.deepEqual(visits[3].sources, ["blob", "url"]);
  assert.ok(visits[2].downloads < visits[1].downloads, JSON.stringify(visits));
});

test("files are stored only after the avatar actually loaded", async () => {
  const { storage, store } = fakeCaches();
  const broken = await loadSdk({ cacheStorage: storage, videoLoadSucceeds: false });
  await assert.rejects(broken.sdk.init({ characterId: "000" }), (error) => error.code === "RESOURCE_LOAD_FAILED");
  await settle();
  // 播不起來的那份不留下來，下次開頁重新下載，而不是一直讀到同一份壞檔。
  assert.equal(store.size, 0);

  const working = await loadSdk({ cacheStorage: storage });
  await working.sdk.init({ characterId: "000" });
  await settle();
  assert.equal(storedKeys(store, "/characters/").length, 2);
  assert.equal(storedKeys(store, "/runtime/").length, 2);
});
