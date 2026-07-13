import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const bundleUrl = new URL("../dist/openvman-avatar-sdk.js", import.meta.url);

async function loadSdk({
  audioState = "running",
  autoEnd = true,
  characterStatus = 200,
  deferDecode = false,
  resumeSucceeds = true,
} = {}) {
  const source = await readFile(bundleUrl, "utf8");
  const script = { src: "https://avatar.example/openvman-avatar-sdk.js" };
  const elements = new Map();
  const requests = [];
  const runtimeCalls = {
    clearAudio: 0,
    pushedAudio: 0,
    resumeCalled: 0,
    scheduledStarts: [],
    sourceStarted: 0,
    sourceStopped: 0,
    videoRemoved: 0,
  };
  let finishDecode;
  let context;
  const createElement = (tagName) => {
    const element = {
      children: [],
      className: "",
      dataset: {},
      parent: null,
      style: { setProperty() {} },
      append(...children) {
        for (const child of children) {
          child.parent = this;
          this.children.push(child);
          if (child.tagName === "script") {
            context.window.characterVideo = {
              load() {},
              play: async () => {},
              remove() {
                runtimeCalls.videoRemoved += 1;
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
    TextDecoder,
    TextEncoder,
    URL,
    Uint8Array,
    console,
    document: {
      body,
      currentScript: script,
      createElement,
      getElementById: (id) => elements.get(id) ?? null,
      head,
    },
    fetch: async (url, options) => {
      requests.push({
        options,
        resumeCalled: runtimeCalls.resumeCalled,
        url,
      });
      const isCharacter = url.includes("combined_data.json.gz");
      return {
        arrayBuffer: async () => new TextEncoder().encode("{}").buffer,
        ok: !isCharacter || characterStatus === 200,
        status: isCharacter ? characterStatus : 200,
      };
    },
    queueMicrotask,
    window: {},
  };
  context.window.AudioContext = class {
    constructor() {
      this.currentTime = 0;
      this.destination = {};
      this.state = audioState;
    }
    async close() {}
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
    requests,
    runtimeCalls,
    sdk: context.window.OpenVmanAvatar,
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
  assert.equal("speak" in avatar, false);
  assert.equal("setPersona" in avatar, false);
});

test("derives resources from the SDK script origin", async () => {
  const { sdk } = await loadSdk();

  assert.equal(sdk.resourceBaseUrl, "https://avatar.example");
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
  const avatar = await sdk.init({ characterId: "000" });
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

test("character failure disposes the created runtime for the page lifetime", async () => {
  const { sdk } = await loadSdk({ characterStatus: 404 });

  await assert.rejects(
    sdk.init({ characterId: "000" }),
    (error) => error.code === "RESOURCE_LOAD_FAILED",
  );
  await assert.rejects(
    sdk.init({ characterId: "000" }),
    (error) => error.code === "RUNTIME_DISPOSED",
  );
});

test("pushPcm queues host chunks in order without backend requests", async () => {
  const { requests, runtimeCalls, sdk } = await loadSdk({ autoEnd: false });
  const avatar = await sdk.init({ characterId: "000" });

  await avatar.pushPcm(new Int16Array(1600));
  await avatar.pushPcm(new Int16Array(800));

  assert.equal(requests.some(({ url }) => url.includes("/api/embed/")), false);
  assert.equal(runtimeCalls.pushedAudio, 2);
  assert.deepEqual(runtimeCalls.scheduledStarts, [0, 0.1]);
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
