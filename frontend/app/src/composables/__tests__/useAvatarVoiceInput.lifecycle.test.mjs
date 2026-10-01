import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { computed, effectScope, nextTick, ref } from "vue";
import * as vue from "vue";
import ts from "typescript";

const source = readFileSync(new URL("../useAvatarVoiceInput.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
});

function openVoice(provider = "r2t2-live") {
  const cleanup = [];
  const engines = {};
  const calls = [];
  const sent = [];
  const timers = new Map();
  let timerId = 0;
  const makeEngine = (name) => (options) => {
    const engine = {
      options,
      isListening: ref(false), isSupported: ref(true),
      isSpeaking: ref(false), isStarting: ref(false), isTranscribing: ref(false),
      start() { calls.push(`${name}:start`); this.isListening.value = true; },
      stop() { calls.push(`${name}:stop`); this.isListening.value = false; },
      pause() { calls.push(`${name}:pause`); },
      resume() { calls.push(`${name}:resume`); },
    };
    engines[name] = engine;
    return engine;
  };
  const dependencies = {
    vue: { ...vue, onUnmounted: (callback) => cleanup.push(callback) },
    "@shared/speech": {
      BROWSER_ASR: "browser",
      isStreamAsrEngine: (id) => ["gemini-live", "r2t2-live"].includes(id),
      getAsrErrorMessage: (id) => id,
    },
    "./useAsr": { useAsr: makeEngine("browser") },
    "./useServerAsr": { useServerAsr: makeEngine("server") },
    "./useVadAsr": { useVadAsr: makeEngine("vad") },
    "./useStreamAsr": { useStreamAsr: makeEngine("stream") },
  };
  const module = { exports: {} };
  new Function("module", "exports", "require", "setTimeout", "clearTimeout", outputText)(
    module, module.exports,
    (name) => {
      assert.ok(dependencies[name], `unexpected dependency ${name}`);
      return dependencies[name];
    },
    (callback, delay) => { timers.set(++timerId, { callback, delay }); return timerId; },
    (id) => timers.delete(id),
  );
  const chat = { state: ref("IDLE") };
  const ttsPending = ref(false);
  const avatarResponding = computed(() => chat.state.value !== "IDLE" || ttsPending.value);
  const taiwaneseOn = ref(false);
  const myAsrProvider = ref(provider);
  const scope = effectScope();
  const voice = scope.run(() => module.exports.useAvatarVoiceInput({
    conversation: {
      chat, avatarResponding,
      async handleSend(...args) { sent.push(args); return { accepted: true }; },
    },
    preferences: { myAsrProvider },
    stage: { triggerStageAvatarGesture: (gesture) => calls.push(gesture) },
    languageRoutes: { taiwaneseOn, asrFormFields: () => ({ project_id: "p1" }) },
    turnTiming: {
      asrDone: () => calls.push("asrDone"),
      speechStarted: () => calls.push("speechStarted"),
      speechEnded: () => calls.push("speechEnded"),
    },
    statusToastRef: ref({ show: (message) => calls.push(message) }),
  }));
  return { voice, engines, calls, sent, timers, chat, ttsPending, taiwaneseOn, myAsrProvider,
    dispose() { cleanup.forEach((fn) => fn()); scope.stop(); } };
}

test("the voice domain selects R2T2 live and preserves Taiwanese batch routing", async () => {
  const app = openVoice();
  try {
    assert.equal(app.voice.activeAsr.value, app.engines.stream);
    app.voice.handleAsrToggle();
    assert.deepEqual(app.calls, ["stream:start"]);
    app.engines.stream.options.onInterim("泵浦");
    assert.equal(app.voice.asrInterim.value, "泵浦");
    assert.equal(app.timers.size, 1);
    app.engines.stream.options.onResult("泵浦在哪裏？");
    await nextTick();
    assert.deepEqual(app.sent, [["泵浦在哪裏？"]]);
    assert.equal(app.voice.asrInterim.value, "");
    assert.equal(app.calls.filter((call) => call === "asrDone").length, 1);
    assert.deepEqual(app.engines.stream.options.query(), { project_id: "p1" });
    app.taiwaneseOn.value = true;
    assert.equal(app.voice.activeAsr.value, app.engines.vad);
    app.myAsrProvider.value = "browser";
    assert.equal(app.voice.activeAsr.value, app.engines.vad);
    app.taiwaneseOn.value = false;
    assert.equal(app.voice.activeAsr.value, app.engines.browser);
  } finally {
    app.dispose();
    assert.equal(app.timers.size, 0);
  }
});

test("stream failure falls back through VAD and recorder without losing language metadata", async () => {
  const app = openVoice();
  try {
    app.engines.stream.options.onError("stream-unavailable");
    assert.equal(app.voice.activeAsr.value, app.engines.vad);
    assert.ok(app.calls.includes("vad:start"));
    app.engines.vad.options.onResult("你好", { language: "nan" });
    await nextTick();
    assert.deepEqual(app.sent[0], ["你好", undefined, undefined, "nan"]);
    app.engines.vad.options.onError("vad-unavailable");
    assert.equal(app.voice.activeAsr.value, app.engines.server);
    assert.ok(app.calls.includes("server:start"));
    assert.equal(app.voice.asrInputMode.value, "push-to-talk");
    assert.equal([...app.timers.values()][0].delay, 60_000);
  } finally { app.dispose(); }
});

test("reply recovery waits for pending TTS and user cancellation disables another recovery", async () => {
  const app = openVoice();
  try {
    app.voice.handleAsrToggle();
    app.chat.state.value = "THINKING";
    await nextTick();
    assert.ok(app.calls.includes("stream:stop"));
    assert.equal(app.timers.size, 0);
    app.ttsPending.value = true;
    app.chat.state.value = "IDLE";
    await nextTick();
    assert.equal(app.calls.filter((call) => call === "stream:start").length, 1);
    app.ttsPending.value = false;
    await nextTick();
    assert.equal(app.calls.filter((call) => call === "stream:start").length, 2);
    assert.equal([...app.timers.values()][0].delay, 6000);
    app.voice.handleAsrToggle();
    app.chat.state.value = "THINKING";
    await nextTick();
    app.chat.state.value = "IDLE";
    await nextTick();
    assert.equal(app.calls.filter((call) => call === "stream:start").length, 2);
  } finally { app.dispose(); }
});
