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
  deferTts = false,
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
    sourceStarted: 0,
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
              HEAPU8: new Uint8Array(1024),
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
      if (deferTts && url.endsWith("/api/embed/tts")) {
        return new Promise((_, reject) => {
          options.signal.addEventListener("abort", () => {
            reject(new DOMException("Aborted", "AbortError"));
          }, { once: true });
        });
      }
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
      this.destination = {};
      this.state = audioState;
    }
    async close() {}
    createBufferSource() {
      const source = {
        connect() {},
        onended: null,
        start() {
          runtimeCalls.sourceStarted += 1;
          if (autoEnd) queueMicrotask(() => source.onended?.());
        },
        stop() {},
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

test("rejects an empty API key with a named public error", async () => {
  const { sdk } = await loadSdk();

  await assert.rejects(
    sdk.init({ apiKey: "" }),
    (error) => error.code === "INVALID_OPTIONS",
  );
});

test("derives resources from the SDK script origin", async () => {
  const { sdk } = await loadSdk();

  assert.equal(sdk.resourceBaseUrl, "https://avatar.example");
});

test("reuses identical init and rejects different page-lifetime init", async () => {
  const { sdk } = await loadSdk();
  const first = await sdk.init({ apiKey: "key_123" });

  assert.equal(await sdk.init({ apiKey: "key_123" }), first);
  await assert.rejects(
    sdk.init({ apiKey: "key_123", characterId: "other" }),
    (error) => error.code === "INSTANCE_EXISTS",
  );
});

test("creates direct DOM, cleans it on destroy, and forbids runtime reuse", async () => {
  const { document, runtimeCalls, sdk } = await loadSdk();
  const avatar = await sdk.init({ apiKey: "key_123" });

  assert.ok(document.getElementById("canvas_video"));
  assert.ok(document.getElementById("canvas_gl"));
  assert.ok(document.getElementById("screen"));
  avatar.destroy();
  assert.equal(document.getElementById("canvas_video"), null);
  assert.equal(runtimeCalls.videoRemoved, 1);
  await assert.rejects(
    sdk.init({ apiKey: "key_123" }),
    (error) => error.code === "RUNTIME_DISPOSED",
  );
});

test("rejects vendor DOM ID conflicts without overwriting the host", async () => {
  const { document, sdk } = await loadSdk();
  const existing = document.createElement("canvas");
  existing.id = "canvas_video";

  await assert.rejects(
    sdk.init({ apiKey: "key_123" }),
    (error) => error.code === "DOM_CONFLICT",
  );
  assert.equal(document.getElementById("canvas_video"), existing);
});

test("speak sends the exact host text to TTS and pushes PCM to the runtime", async () => {
  const { requests, runtimeCalls, sdk } = await loadSdk();
  const avatar = await sdk.init({ apiKey: "key_123" });
  const states = [];
  avatar.on("speaking", (event) => states.push(event.state));

  await avatar.speak("這款商品目前有優惠");

  const ttsRequest = requests.find(({ url }) => url.endsWith("/api/embed/tts"));
  assert.deepEqual(JSON.parse(ttsRequest.options.body), {
    text: "這款商品目前有優惠",
  });
  assert.equal(ttsRequest.options.headers.Authorization, "Bearer key_123");
  assert.ok(runtimeCalls.pushedAudio > 0);
  assert.deepEqual(states, ["start", "stop"]);
});

test("speak reports autoplay blocking with a named error event", async () => {
  const { sdk } = await loadSdk({
    audioState: "suspended",
    resumeSucceeds: false,
  });
  const avatar = await sdk.init({ apiKey: "key_123" });
  const errors = [];
  avatar.on("error", (event) => errors.push(event.code));

  await assert.rejects(
    avatar.speak("需要點擊後播放"),
    (error) => error.code === "AUTOPLAY_BLOCKED",
  );
  assert.deepEqual(errors, ["AUTOPLAY_BLOCKED"]);
});

test("interrupt stops pending speech and clears the runtime", async () => {
  const { runtimeCalls, sdk } = await loadSdk({ autoEnd: false });
  const avatar = await sdk.init({ apiKey: "key_123" });
  const states = [];
  avatar.on("speaking", (event) => states.push(event.state));
  const speech = avatar.speak("停止這段語音");
  await new Promise((resolve) => setImmediate(resolve));

  avatar.interrupt();
  await Promise.race([
    speech,
    new Promise((_, reject) => setTimeout(
      () => reject(new Error("interrupted speech did not settle")),
      20,
    )),
  ]);

  assert.deepEqual(states, ["start", "stop"]);
  assert.ok(runtimeCalls.clearAudio > 0);
});

test("interrupt aborts an in-flight TTS request without emitting an error", async () => {
  const { sdk } = await loadSdk({ deferTts: true });
  const avatar = await sdk.init({ apiKey: "key_123" });
  const events = [];
  avatar.on("error", (event) => events.push(event));
  const speech = avatar.speak("尚未產生完成的語音");
  await new Promise((resolve) => setImmediate(resolve));

  avatar.interrupt();
  await speech;

  assert.deepEqual(events, []);
});

test("unlocks audio synchronously before starting the TTS request", async () => {
  const { requests, runtimeCalls, sdk } = await loadSdk({
    audioState: "suspended",
  });
  const avatar = await sdk.init({ apiKey: "key_123" });

  await avatar.speak("由點擊事件觸發的首句");

  assert.equal(runtimeCalls.resumeCalled, 1);
  assert.equal(
    requests.find(({ url }) => url.endsWith("/api/embed/tts")).resumeCalled,
    1,
  );
});

test("interrupt during decode prevents PCM and source playback", async () => {
  const { finishDecode, runtimeCalls, sdk } = await loadSdk({
    deferDecode: true,
  });
  const avatar = await sdk.init({ apiKey: "key_123" });
  const speech = avatar.speak("正在解碼的語音");
  await new Promise((resolve) => setImmediate(resolve));

  avatar.interrupt();
  finishDecode();
  await speech;

  assert.equal(runtimeCalls.pushedAudio, 0);
  assert.equal(runtimeCalls.sourceStarted, 0);
});

test("different persona or container is treated as a different init", async () => {
  const { document, sdk } = await loadSdk();
  const firstContainer = document.createElement("section");
  const secondContainer = document.createElement("section");
  await sdk.init({
    apiKey: "key_123",
    container: firstContainer,
    persona: "sales",
  });

  await assert.rejects(
    sdk.init({
      apiKey: "key_123",
      container: secondContainer,
      persona: "sales",
    }),
    (error) => error.code === "INSTANCE_EXISTS",
  );
  await assert.rejects(
    sdk.init({
      apiKey: "key_123",
      container: firstContainer,
      persona: "support",
    }),
    (error) => error.code === "INSTANCE_EXISTS",
  );
});

test("character failure disposes the created runtime for the page lifetime", async () => {
  const { sdk } = await loadSdk({ characterStatus: 404 });

  await assert.rejects(
    sdk.init({ apiKey: "key_123" }),
    (error) => error.code === "RESOURCE_LOAD_FAILED",
  );
  await assert.rejects(
    sdk.init({ apiKey: "key_123" }),
    (error) => error.code === "RUNTIME_DISPOSED",
  );
});
