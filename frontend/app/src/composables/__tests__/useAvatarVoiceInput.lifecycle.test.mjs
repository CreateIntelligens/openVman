import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { computed, effectScope, nextTick, ref } from "vue";
import * as vue from "vue";
import ts from "typescript";

const source = readFileSync(new URL("../useAvatarVoiceInput.ts", import.meta.url), "utf8");
const transpile = (text) => ts.transpileModule(text, {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText;
const FLAG = "const INTERRUPT_WHILE_SPEAKING = false;";
assert.ok(source.includes(FLAG), "講話中插話預設要關著，等現場回音實測後再開");
const outputs = {
  off: transpile(source),
  // 階段 B 的程式還在，開關打開時的行為照樣要測，免得之後要開時才發現壞了。
  on: transpile(source.replace(FLAG, "const INTERRUPT_WHILE_SPEAKING = true;")),
};

function openVoice(provider = "r2t2-live", decision = "IGNORE", { interruptWhileSpeaking = false } = {}) {
  const outputText = outputs[interruptWhileSpeaking ? "on" : "off"];
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
      stop() { calls.push(`${name}:stop`); this.isListening.value = false; this.isStarting.value = false; },
      pause() { calls.push(`${name}:pause`); },
      resume() { calls.push(`${name}:resume`); },
    };
    engines[name] = engine;
    return engine;
  };
  const dependencies = {
    "../api/http": { apiFetch: async () => ({ ok: true, json: async () => ({ action: decision }) }) },
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
  const avatarSpeaking = computed(() => chat.state.value === "SPEAKING" || ttsPending.value);
  const avatarResponding = computed(() => chat.state.value === "THINKING" || avatarSpeaking.value);
  const taiwaneseOn = ref(false);
  const myAsrProvider = ref(provider);
  const scope = effectScope();
  const voice = scope.run(() => module.exports.useAvatarVoiceInput({
    conversation: {
      chat, avatarSpeaking, avatarResponding, spokenReply: ref("原本回答"),
      handleStopResponse() { calls.push("interrupt"); ttsPending.value = false; chat.state.value = "IDLE"; },
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
    // 在想時麥克風照開（可以補一句），只是不倒數。
    assert.ok(!app.calls.includes("stream:stop"));
    assert.equal(app.timers.size, 0);
    app.ttsPending.value = true;
    app.chat.state.value = "IDLE";
    await nextTick();
    // 開始出聲才關，免得收到自己的聲音。
    assert.ok(app.calls.includes("stream:stop"));
    assert.equal(app.calls.filter((call) => call === "stream:start").length, 1);
    app.ttsPending.value = false;
    await nextTick();
    assert.equal(app.calls.filter((call) => call === "stream:start").length, 2);
    assert.equal([...app.timers.values()][0].delay, 6000);
    app.voice.handleAsrToggle();
    app.chat.state.value = "THINKING";
    await nextTick();
    app.ttsPending.value = true;
    app.chat.state.value = "IDLE";
    await nextTick();
    app.ttsPending.value = false;
    await nextTick();
    assert.equal(app.calls.filter((call) => call === "stream:start").length, 2);
  } finally { app.dispose(); }
});

test("a sentence added while thinking is sent and does not restart the idle countdown", async () => {
  const app = openVoice();
  try {
    app.voice.handleAsrToggle();
    app.engines.stream.options.onResult("沉水泵多深？");
    app.chat.state.value = "THINKING";
    await nextTick();
    assert.equal(app.timers.size, 0);
    app.engines.stream.options.onInterim("還有");
    app.engines.stream.options.onResult("還有馬力多大？");
    await nextTick();
    assert.deepEqual(app.sent, [["沉水泵多深？"], ["還有馬力多大？"]]);
    assert.equal(app.timers.size, 0, "思考中不倒數，免得等回答時麥克風自己關掉");
    assert.ok(app.engines.stream.isListening.value);
  } finally { app.dispose(); }
});

test("Breeze VAD keeps listening through thinking and pauses only while the avatar speaks", async () => {
  const app = openVoice("breeze");
  try {
    assert.equal(app.voice.activeAsr.value, app.engines.vad);
    app.voice.handleAsrToggle();
    app.engines.vad.options.onResult("沉水泵多深？", { language: "zh" });
    app.chat.state.value = "THINKING";
    await nextTick();
    assert.ok(!app.calls.includes("vad:pause"));
    app.engines.vad.options.onResult("還有馬力多大？", { language: "zh" });
    await nextTick();
    assert.equal(app.sent.length, 2);
    app.ttsPending.value = true;
    app.chat.state.value = "IDLE";
    await nextTick();
    assert.ok(app.calls.includes("vad:pause"));
    app.ttsPending.value = false;
    await nextTick();
    assert.equal(app.calls.at(-1), "vad:resume");
  } finally { app.dispose(); }
});

test("a long VAD sentence is not stopped by the idle timeout", async () => {
  const app = openVoice("breeze");
  try {
    app.voice.handleAsrToggle();
    app.engines.vad.isSpeaking.value = true;
    await nextTick();
    const [{ callback }] = [...app.timers.values()];
    app.timers.clear(); callback();
    assert.ok(app.engines.vad.isListening.value);
    assert.ok(!app.calls.includes("vad:stop"));
    assert.equal(app.timers.size, 1);
    app.engines.vad.isSpeaking.value = false;
    await nextTick();
    const [idle] = [...app.timers.values()];
    app.timers.clear(); idle.callback();
    assert.equal(app.engines.vad.isListening.value, false);
  } finally { app.dispose(); }
});

test("an ASR start pending when playback begins is cancelled and recovered once", async () => {
  const app = openVoice();
  try {
    app.engines.stream.isStarting.value = true;
    app.ttsPending.value = true;
    await nextTick();
    assert.ok(app.calls.includes("stream:stop"));
    app.ttsPending.value = false;
    await nextTick();
    assert.equal(app.calls.filter((call) => call === "stream:start").length, 1);
  } finally { app.dispose(); }
});

test("with interruptions on, an ASR start pending when playback begins remains available", async () => {
  const app = openVoice("r2t2-live", "IGNORE", { interruptWhileSpeaking: true });
  try {
    app.engines.stream.isStarting.value = true;
    app.ttsPending.value = true;
    await nextTick();
    assert.ok(!app.calls.includes("stream:stop"));
    app.ttsPending.value = false;
    await nextTick();
    assert.equal(app.calls.filter((call) => call === "stream:start").length, 0);
  } finally { app.dispose(); }
});

for (const decision of ["STOP", "IGNORE"]) {
  test(`streaming playback handles ${decision} without closing the microphone`, async () => {
    const app = openVoice("r2t2-live", decision, { interruptWhileSpeaking: true });
    try {
      app.voice.handleAsrToggle();
      app.ttsPending.value = true;
      await nextTick();
      app.engines.stream.options.onResult("等一下");
      await new Promise(resolve => setImmediate(resolve));
      assert.ok(app.engines.stream.isListening.value);
      assert.equal(app.calls.includes("interrupt"), decision === "STOP");
      assert.equal(app.sent.length, decision === "STOP" ? 1 : 0);
      assert.equal(app.timers.size, decision === "STOP" ? 1 : 0);
    } finally { app.dispose(); }
  });
}
