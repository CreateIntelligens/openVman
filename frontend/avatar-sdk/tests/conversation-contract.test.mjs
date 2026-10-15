import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const bundleUrl = new URL("../dist/openvman-avatar-sdk.js", import.meta.url);

/**
 * Mirrors the public-contract harness, adding chat/speech stubs so the
 * conversation path can be exercised without a backend.
 */
async function loadSdk({
  chatBody = { reply: "你好，我是 openVman。" },
  chatHeaders = {},
  chatStatus = 200,
  deferChat = false,
  manualStream = false,
  speechDelayMs = 0,
  speechStatus = 200,
  streamEvents,
  streamStatus = chatStatus,
  withCryptoUuid = true,
} = {}) {
  const source = await readFile(bundleUrl, "utf8");
  const script = { src: "https://avatar.example/static/sdk/openvman-avatar-sdk.js" };
  const elements = new Map();
  const requests = [];
  const runtimeCalls = {
    clearAudio: 0,
    pushedAudio: 0,
    sourceStarted: 0,
    sourceStopped: 0,
    speakerOutput: 0,
    silentOutput: 0,
  };
  let finishChat;
  let stream = null;
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
            const videoListeners = new Map();
            context.window.characterVideo = {
              addEventListener(type, handler) {
                const handlers = videoListeners.get(type) ?? new Set();
                handlers.add(handler);
                videoListeners.set(type, handlers);
              },
              error: null,
              load() {
                queueMicrotask(() => {
                  this.readyState = 3;
                  for (const handler of videoListeners.get("canplay") ?? []) {
                    handler();
                  }
                });
              },
              play: async () => {},
              readyState: 0,
              remove() {},
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
      element.getContext = () => ({
        globalAlpha: 1,
        clearRect() {},
        drawImage() {},
      });
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
  const makeHeaders = (values) => ({
    get: (name) => {
      const key = Object.keys(values).find(
        (candidate) => candidate.toLowerCase() === name.toLowerCase(),
      );
      return key ? values[key] : null;
    },
  });
  context = {
    AbortController,
    HTMLMediaElement: { HAVE_CURRENT_DATA: 2 },
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
      requests.push({ options, url });
      if (String(url).endsWith("/api/v1/chat/stream")) {
        const respond = () => {
          if (streamStatus !== 200) {
            return {
              headers: makeHeaders(chatHeaders),
              ok: false,
              status: streamStatus,
            };
          }
          stream = createSseStream(options.signal);
          if (!manualStream) {
            for (const item of streamEvents ?? defaultStreamEvents(chatBody)) {
              stream.push(item.event, item.data);
            }
            stream.end();
          }
          return {
            body: stream.body,
            headers: makeHeaders({}),
            ok: true,
            status: 200,
          };
        };
        if (!deferChat) return respond();
        return new Promise((resolve) => {
          finishChat = () => resolve(respond());
        });
      }
      if (String(url).endsWith("/api/v1/chat")) {
        const respond = () => ({
          arrayBuffer: async () => new TextEncoder().encode("{}").buffer,
          headers: makeHeaders(chatHeaders),
          json: async () => chatBody,
          ok: chatStatus === 200,
          status: chatStatus,
        });
        if (!deferChat) return respond();
        return new Promise((resolve) => {
          finishChat = () => resolve(respond());
        });
      }
      if (String(url).endsWith("/v1/audio/speech")) {
        if (speechDelayMs) {
          await new Promise((resolve) => setTimeout(resolve, speechDelayMs));
        }
        return {
          arrayBuffer: async () => new ArrayBuffer(32),
          headers: makeHeaders({}),
          ok: speechStatus === 200,
          status: speechStatus,
        };
      }
      if (String(url).endsWith("/characters")) {
        return {
          headers: makeHeaders({}),
          json: async () => ({ characters: [] }),
          ok: true,
          status: 200,
        };
      }
      return {
        arrayBuffer: async () => new TextEncoder().encode("{}").buffer,
        headers: makeHeaders({}),
        ok: true,
        status: 200,
      };
    },
    queueMicrotask,
    performance: { now: () => 0 },
    window: { clearTimeout, setTimeout },
  };
  if (withCryptoUuid) {
    context.crypto = { randomUUID: () => globalThis.crypto.randomUUID() };
  }
  context.window.AudioContext = class {
    constructor() {
      this.currentTime = 0;
      this.destination = { kind: "destination" };
      this.state = "running";
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
        connect(target) {
          if (target?.kind === "mute") runtimeCalls.silentOutput += 1;
          if (target?.kind === "destination") runtimeCalls.speakerOutput += 1;
        },
        onended: null,
        start() {
          runtimeCalls.sourceStarted += 1;
          queueMicrotask(() => source.onended?.());
        },
        stop() {
          runtimeCalls.sourceStopped += 1;
        },
      };
      return source;
    }
    createGain() {
      return { connect() {}, gain: { value: 1 }, kind: "mute" };
    }
    async decodeAudioData() {
      return {
        getChannelData: () => new Float32Array([0, 0.5, -0.5, 0]),
        length: 4,
        numberOfChannels: 1,
        sampleRate: 16000,
      };
    }
    async resume() {
      this.state = "running";
    }
  };
  context.globalThis = context;
  vm.runInNewContext(source, context);
  return {
    document: context.document,
    finishChat: () => finishChat?.(),
    requests,
    stream: () => stream,
    runtimeCalls,
    sdk: context.window.OpenVmanAvatar,
  };
}

function defaultStreamEvents(chatBody) {
  return [
    { data: { index: 0, text: chatBody.reply }, event: "sentence" },
    { data: chatBody, event: "done" },
  ];
}

/** A text/event-stream body the test can feed one event at a time. */
function createSseStream(signal) {
  const encoder = new TextEncoder();
  const chunks = [];
  let ended = false;
  let waiting = null;
  let failure = null;
  const wake = () => {
    const next = waiting;
    waiting = null;
    next?.();
  };
  signal?.addEventListener("abort", () => {
    failure = new Error("The operation was aborted.");
    wake();
  });
  const reader = {
    async cancel() {
      ended = true;
      wake();
    },
    async read() {
      for (;;) {
        if (failure) throw failure;
        if (chunks.length) return { done: false, value: chunks.shift() };
        if (ended) return { done: true, value: undefined };
        await new Promise((resolve) => {
          waiting = resolve;
        });
      }
    },
  };
  return {
    body: { getReader: () => reader },
    end() {
      ended = true;
      wake();
    },
    push(event, data) {
      chunks.push(
        encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`),
      );
      wake();
    },
  };
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

const streamRequests = (requests) =>
  requests.filter(({ url }) => String(url).endsWith("/api/v1/chat/stream"));
const wholeChatRequests = (requests) =>
  requests.filter(({ url }) => String(url).endsWith("/api/v1/chat"));
const chatRequests = (requests) =>
  [...streamRequests(requests), ...wholeChatRequests(requests)];
const speechRequests = (requests) =>
  requests.filter(({ url }) => String(url).endsWith("/v1/audio/speech"));

test("a legacy host makes no chat or speech request", async () => {
  const { requests, sdk } = await loadSdk();
  const avatar = await sdk.init({ characterId: "000" });

  await avatar.playAudio(new ArrayBuffer(16));

  assert.equal(chatRequests(requests).length, 0);
  assert.equal(speechRequests(requests).length, 0);
  assert.equal(typeof avatar.ask, "function");
});

test("conversation options take part in the instance signature", async () => {
  const { sdk } = await loadSdk();
  const first = await sdk.init({ characterId: "000", projectId: "alpha" });

  assert.equal(
    await sdk.init({ characterId: "000", projectId: "alpha" }),
    first,
  );
  await assert.rejects(
    sdk.init({ characterId: "000", projectId: "beta" }),
    (error) => error.code === "INSTANCE_EXISTS",
  );
  await assert.rejects(
    sdk.init({ characterId: "000", projectId: "alpha", embedKey: "ovk_x" }),
    (error) => error.code === "INSTANCE_EXISTS",
  );
});

test("a keyed host sends X-Embed-Key without credentials and speaks the reply", async () => {
  const { requests, runtimeCalls, sdk } = await loadSdk();
  const avatar = await sdk.init({
    characterId: "000",
    embedKey: "ovk_demo",
    personaId: "guide",
    projectId: "alpha",
    tts: { provider: "voxcpm", voice: "zh-female" },
  });
  const replies = [];
  avatar.on("reply", (event) => replies.push(event.text));

  const reply = await avatar.ask("你好");

  assert.equal(reply, "你好，我是 openVman。");
  assert.deepEqual(replies, ["你好，我是 openVman。"]);

  const [chat] = chatRequests(requests);
  assert.equal(chat.options.method, "POST");
  assert.equal(chat.options.headers["X-Embed-Key"], "ovk_demo");
  assert.equal(chat.options.credentials, "omit");
  const chatPayload = JSON.parse(chat.options.body);
  assert.equal(chatPayload.message, "你好");
  assert.equal(chatPayload.project_id, "alpha");
  assert.equal(chatPayload.persona_id, "guide");
  assert.equal(typeof chatPayload.session_id, "string");

  const [speech] = speechRequests(requests);
  assert.equal(speech.options.headers["X-Embed-Key"], "ovk_demo");
  assert.equal(speech.options.credentials, "omit");
  assert.deepEqual(JSON.parse(speech.options.body), {
    input: "你好，我是 openVman。",
    provider: "voxcpm",
    voice: "zh-female",
  });

  assert.ok(runtimeCalls.pushedAudio > 0);
  assert.ok(runtimeCalls.sourceStarted > 0);
});

test("a same-origin session host sends credentials and no embed key", async () => {
  const { requests, sdk } = await loadSdk();
  const avatar = await sdk.init({ characterId: "000", projectId: "alpha" });

  await avatar.ask("你好");

  for (const request of [...chatRequests(requests), ...speechRequests(requests)]) {
    assert.equal(request.options.credentials, "include");
    assert.equal("X-Embed-Key" in request.options.headers, false);
  }
  // 未設定的選項不應出現在 payload 中。
  const chatPayload = JSON.parse(chatRequests(requests)[0].options.body);
  assert.equal("persona_id" in chatPayload, false);
  assert.deepEqual(JSON.parse(speechRequests(requests)[0].options.body), {
    input: "你好，我是 openVman。",
  });
});

test("every turn on one instance reuses the same session id", async () => {
  const { requests, sdk } = await loadSdk();
  const avatar = await sdk.init({ characterId: "000" });

  await avatar.ask("第一句");
  await avatar.ask("第二句");
  await avatar.ask("第三句");

  const sessionIds = chatRequests(requests).map(
    ({ options }) => JSON.parse(options.body).session_id,
  );
  assert.equal(sessionIds.length, 3);
  assert.equal(new Set(sessionIds).size, 1);
  assert.ok(sessionIds[0]);
});

test("a session id is still created without crypto.randomUUID", async () => {
  const { requests, sdk } = await loadSdk({ withCryptoUuid: false });
  const avatar = await sdk.init({ characterId: "000" });

  await avatar.ask("你好");

  const { session_id: sessionId } = JSON.parse(
    chatRequests(requests)[0].options.body,
  );
  assert.equal(typeof sessionId, "string");
  assert.ok(sessionId.length > 0);
});

test("a new ask interrupts playback still running from the previous turn", async () => {
  const { finishChat, runtimeCalls, sdk } = await loadSdk({ deferChat: true });
  const avatar = await sdk.init({ characterId: "000" });
  const first = avatar.ask("第一句");
  finishChat();
  await first;

  const clearedBefore = runtimeCalls.clearAudio;
  const second = avatar.ask("第二句");
  // interrupt 必須在送出新一輪 chat 之前就發生。
  assert.ok(runtimeCalls.clearAudio > clearedBefore);
  finishChat();
  await second;
});

test("a rejected key fails with UNAUTHORIZED and never requests speech", async () => {
  const { requests, sdk } = await loadSdk({ chatStatus: 401 });
  const avatar = await sdk.init({ characterId: "000", embedKey: "ovk_revoked" });
  const errors = [];
  avatar.on("error", (event) => errors.push(event));

  await assert.rejects(
    avatar.ask("你好"),
    (error) => error.code === "UNAUTHORIZED",
  );

  assert.equal(speechRequests(requests).length, 0);
  assert.deepEqual(errors.map(({ code }) => code), ["UNAUTHORIZED"]);
});

test("a forbidden request also maps to UNAUTHORIZED", async () => {
  const { sdk } = await loadSdk({ chatStatus: 403 });
  const avatar = await sdk.init({ characterId: "000", embedKey: "ovk_demo" });

  await assert.rejects(
    avatar.ask("你好"),
    (error) => error.code === "UNAUTHORIZED",
  );
});

test("an exhausted quota fails with RATE_LIMITED and Retry-After seconds", async () => {
  const { sdk } = await loadSdk({
    chatHeaders: { "Retry-After": "30" },
    chatStatus: 429,
  });
  const avatar = await sdk.init({ characterId: "000", embedKey: "ovk_demo" });
  const errors = [];
  avatar.on("error", (event) => errors.push(event));

  await assert.rejects(
    avatar.ask("你好"),
    (error) => error.code === "RATE_LIMITED" && error.retryAfterSeconds === 30,
  );

  assert.equal(errors[0].code, "RATE_LIMITED");
  assert.equal(errors[0].retryAfterSeconds, 30);
});

test("a 429 without Retry-After omits retryAfterSeconds", async () => {
  const { sdk } = await loadSdk({ chatStatus: 429 });
  const avatar = await sdk.init({ characterId: "000" });

  await assert.rejects(
    avatar.ask("你好"),
    (error) =>
      error.code === "RATE_LIMITED" && error.retryAfterSeconds === undefined,
  );
});

test("other chat failures report CHAT_FAILED", async () => {
  const { sdk } = await loadSdk({ chatStatus: 502 });
  const avatar = await sdk.init({ characterId: "000" });

  await assert.rejects(
    avatar.ask("你好"),
    (error) => error.code === "CHAT_FAILED",
  );
});

test("speech failures report SPEECH_FAILED after the reply event", async () => {
  const { sdk } = await loadSdk({ speechStatus: 502 });
  const avatar = await sdk.init({ characterId: "000" });
  const replies = [];
  const errors = [];
  avatar.on("reply", (event) => replies.push(event.text));
  avatar.on("error", (event) => errors.push(event.code));

  await assert.rejects(
    avatar.ask("你好"),
    (error) => error.code === "SPEECH_FAILED",
  );

  assert.deepEqual(replies, ["你好，我是 openVman。"]);
  assert.deepEqual(errors, ["SPEECH_FAILED"]);
});

test("a silent instance drives lip sync through the runtime without sound", async () => {
  const { runtimeCalls, sdk } = await loadSdk();
  const avatar = await sdk.init({ audioOutput: "silent", characterId: "000" });

  const reply = await avatar.ask("你好");

  assert.equal(reply, "你好，我是 openVman。");
  assert.ok(runtimeCalls.pushedAudio > 0);
  assert.equal(runtimeCalls.silentOutput > 0, true);
  assert.equal(runtimeCalls.speakerOutput, 0);
});

test("ask streams the reply and speaks the first sentence before done", async () => {
  const { requests, sdk, stream } = await loadSdk({ manualStream: true });
  const avatar = await sdk.init({ characterId: "000", embedKey: "ovk_demo" });
  const sentences = [];
  const replies = [];
  avatar.on("sentence", (event) => sentences.push([event.index, event.text]));
  avatar.on("reply", (event) => replies.push(event.text));

  const pending = avatar.ask("你好");
  await flush();
  const [chat] = streamRequests(requests);
  assert.equal(chat.options.headers["X-Embed-Key"], "ovk_demo");
  assert.equal(chat.options.credentials, "omit");
  assert.equal(JSON.parse(chat.options.body).message, "你好");

  stream().push("sentence", { index: 0, text: "第一句。" });
  await flush();
  // done 還沒到就已經在合成第一句。
  assert.deepEqual(
    speechRequests(requests).map(({ options }) => JSON.parse(options.body).input),
    ["第一句。"],
  );
  assert.deepEqual(replies, []);

  stream().push("sentence", { index: 1, text: "第二句。" });
  stream().push("done", { reply: "第一句。第二句。" });
  stream().end();

  assert.equal(await pending, "第一句。第二句。");
  assert.deepEqual(sentences, [[0, "第一句。"], [1, "第二句。"]]);
  assert.deepEqual(replies, ["第一句。第二句。"]);
  assert.equal(
    speechRequests(requests).map(({ options }) => JSON.parse(options.body).input).join(""),
    "第一句。第二句。",
  );
  assert.equal(wholeChatRequests(requests).length, 0);
});

test("sentences arriving during synthesis join the next speech request", async () => {
  const { requests, sdk } = await loadSdk({
    speechDelayMs: 5,
    streamEvents: [
      { data: { index: 0, text: "一。" }, event: "sentence" },
      { data: { index: 1, text: "二。" }, event: "sentence" },
      { data: { index: 2, text: "三。" }, event: "sentence" },
      { data: { reply: "一。二。三。" }, event: "done" },
    ],
  });
  const avatar = await sdk.init({ characterId: "000" });

  await avatar.ask("數數");

  const inputs = speechRequests(requests).map(
    ({ options }) => JSON.parse(options.body).input,
  );
  assert.deepEqual(inputs, ["一。", "二。三。"]);
});

test("a stream without sentences still speaks the final reply", async () => {
  const { requests, sdk } = await loadSdk({
    streamEvents: [{ data: { reply: "只有完整回答。" }, event: "done" }],
  });
  const avatar = await sdk.init({ characterId: "000" });

  assert.equal(await avatar.ask("你好"), "只有完整回答。");
  assert.deepEqual(
    speechRequests(requests).map(({ options }) => JSON.parse(options.body).input),
    ["只有完整回答。"],
  );
});

test("a missing stream route falls back to /chat for the rest of the instance", async () => {
  const { requests, sdk } = await loadSdk({ streamStatus: 404 });
  const avatar = await sdk.init({ characterId: "000" });

  assert.equal(await avatar.ask("第一句"), "你好，我是 openVman。");
  assert.equal(await avatar.ask("第二句"), "你好，我是 openVman。");

  assert.equal(streamRequests(requests).length, 1);
  assert.equal(wholeChatRequests(requests).length, 2);
  const sessionIds = chatRequests(requests).map(
    ({ options }) => JSON.parse(options.body).session_id,
  );
  assert.equal(new Set(sessionIds).size, 1);
});

test("a 404 from both routes is a chat failure and keeps trying the stream", async () => {
  const { requests, sdk } = await loadSdk({ chatStatus: 404 });
  const avatar = await sdk.init({ characterId: "000" });

  await assert.rejects(avatar.ask("一"), (error) => error.code === "CHAT_FAILED");
  await assert.rejects(avatar.ask("二"), (error) => error.code === "CHAT_FAILED");

  assert.equal(streamRequests(requests).length, 2);
});

for (const [status, detail, code, retryAfterSeconds] of [
  [429, { retry_after_ms: 3000 }, "RATE_LIMITED", 3],
  [403, "forbidden", "UNAUTHORIZED", undefined],
  [502, { error_code: "LLM_OVERLOAD", retry_after_ms: 3000 }, "CHAT_FAILED", undefined],
]) {
  test(`a stream error event with status ${status} maps to ${code}`, async () => {
    const { requests, sdk } = await loadSdk({
      streamEvents: [{ data: { detail, status }, event: "error" }],
    });
    const avatar = await sdk.init({ characterId: "000" });
    const replies = [];
    avatar.on("reply", (event) => replies.push(event.text));

    await assert.rejects(
      avatar.ask("你好"),
      (error) =>
        error.code === code && error.retryAfterSeconds === retryAfterSeconds,
    );
    assert.deepEqual(replies, []);
    assert.equal(speechRequests(requests).length, 0);
  });
}

test("a stream that ends without done fails with CHAT_FAILED", async () => {
  const { sdk } = await loadSdk({
    streamEvents: [{ data: { index: 0, text: "說到一半" }, event: "sentence" }],
  });
  const avatar = await sdk.init({ characterId: "000" });

  await assert.rejects(avatar.ask("你好"), (error) => error.code === "CHAT_FAILED");
});

test("interrupt mid-stream aborts the stream and requests no more speech", async () => {
  const { requests, sdk, stream } = await loadSdk({ manualStream: true });
  const avatar = await sdk.init({ characterId: "000" });
  const replies = [];
  avatar.on("reply", (event) => replies.push(event.text));

  const pending = avatar.ask("你好");
  await flush();
  stream().push("sentence", { index: 0, text: "第一句。" });
  await flush();
  const speechBefore = speechRequests(requests).length;

  avatar.interrupt();
  stream().push("sentence", { index: 1, text: "第二句。" });
  stream().push("done", { reply: "第一句。第二句。" });

  // 中斷時回傳已經收到的部分，不派送 reply。
  assert.equal(await pending, "第一句。");
  await flush();
  assert.equal(streamRequests(requests)[0].options.signal.aborted, true);
  assert.equal(speechRequests(requests).length, speechBefore);
  assert.deepEqual(replies, []);
});

test("a new ask aborts the previous stream", async () => {
  const { requests, sdk, stream } = await loadSdk({ manualStream: true });
  const avatar = await sdk.init({ characterId: "000" });

  const first = avatar.ask("第一題");
  await flush();
  const firstStream = stream();
  firstStream.push("sentence", { index: 0, text: "舊的。" });
  await flush();

  const second = avatar.ask("第二題");
  assert.equal(await first, "舊的。");
  await flush();
  stream().push("sentence", { index: 0, text: "新的。" });
  stream().push("done", { reply: "新的。" });
  stream().end();
  assert.equal(await second, "新的。");

  assert.equal(streamRequests(requests)[0].options.signal.aborted, true);
  assert.equal(streamRequests(requests).length, 2);
});

test("a speech failure mid-stream still reports the reply before SPEECH_FAILED", async () => {
  const { sdk } = await loadSdk({ speechStatus: 502 });
  const avatar = await sdk.init({ characterId: "000" });
  const events = [];
  avatar.on("reply", () => events.push("reply"));
  avatar.on("error", (event) => events.push(event.code));

  await assert.rejects(avatar.ask("你好"), (error) => error.code === "SPEECH_FAILED");
  assert.deepEqual(events, ["reply", "SPEECH_FAILED"]);
});
