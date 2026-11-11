import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import ts from "typescript";

const source = readFileSync(new URL("../src/audio.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
}).outputText;
const { AvatarAudio } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

function deferred() {
  let resolve;
  const promise = new Promise((next) => { resolve = next; });
  return { promise, resolve };
}

function fakeRuntime() {
  const calls = [];
  const runtime = {
    audioContext: {
      async decodeAudioData(encoded) {
        calls.push(`decode:${new Uint8Array(encoded)[0]}`);
        return {
          length: 8192,
          sampleRate: 16000,
          numberOfChannels: 1,
          getChannelData: () => new Float32Array(8192),
        };
      },
    },
    clearAudio() { calls.push("stop"); },
    async finishAudio() { calls.push("finish"); },
    onSpeakingChange() { return () => {}; },
    async prepare() { calls.push("prepare"); },
    async pushAudio() { calls.push("append"); },
  };
  return { calls, runtime };
}

test("encoded audio awaits each engine append and actual drain", async () => {
  const { calls, runtime } = fakeRuntime();
  const append = deferred();
  const drain = deferred();
  let count = 0;
  runtime.pushAudio = async () => {
    calls.push("append");
    if (++count === 1) await append.promise;
  };
  runtime.finishAudio = async () => { calls.push("finish"); await drain.promise; };
  const audio = new AvatarAudio(runtime, () => {});
  let done = false;
  const playback = audio.playAudio(new Uint8Array([1]).buffer).then(() => { done = true; });
  await new Promise(setImmediate);
  assert.equal(calls.filter((call) => call === "append").length, 1);
  assert.equal(calls.includes("finish"), false);
  append.resolve();
  await new Promise(setImmediate);
  assert.equal(calls.filter((call) => call === "append").length, 2);
  assert.equal(done, false);
  drain.resolve();
  await playback;
  assert.equal(done, true);
});

test("queued encoded segments preserve order through drain", async () => {
  const { calls, runtime } = fakeRuntime();
  const drain = deferred();
  let drains = 0;
  runtime.finishAudio = async () => { if (++drains === 1) await drain.promise; };
  const audio = new AvatarAudio(runtime, () => {});
  const first = audio.queueAudio(new Uint8Array([1]).buffer);
  const second = audio.queueAudio(new Uint8Array([2]).buffer);
  await new Promise(setImmediate);
  assert.deepEqual(calls.filter((call) => call.startsWith("decode:")), ["decode:1"]);
  drain.resolve();
  await Promise.all([first, second]);
  assert.deepEqual(calls.filter((call) => call.startsWith("decode:")), ["decode:1", "decode:2"]);
});

test("interrupt during engine backpressure prevents stale chunks and EOS", async () => {
  const { calls, runtime } = fakeRuntime();
  const append = deferred();
  runtime.pushAudio = async () => { calls.push("append"); await append.promise; };
  const audio = new AvatarAudio(runtime, () => {});
  const playback = audio.playAudio(new Uint8Array([1]).buffer);
  await new Promise(setImmediate);
  audio.interrupt();
  append.resolve();
  await playback;
  assert.equal(calls.filter((call) => call === "append").length, 1);
  assert.equal(calls.includes("finish"), false);
});

test("SDK delegates all scheduling to the engine", () => {
  assert.doesNotMatch(source, /createBufferSource|new AudioContext|\.start\(|\.createGain\(/);
});

test("raw PCM idle flush sends EOS and interrupt cancels a stale flush", async () => {
  const { calls, runtime } = fakeRuntime();
  const timers = new Map();
  let nextId = 0;
  const previousWindow = globalThis.window;
  globalThis.window = {
    clearTimeout(id) { timers.delete(id); },
    setTimeout(callback) {
      const id = ++nextId;
      timers.set(id, () => { timers.delete(id); callback(); });
      return id;
    },
  };
  try {
    const chunks = [];
    runtime.pushAudio = async (pcm) => { chunks.push(pcm.length); };
    const audio = new AvatarAudio(runtime, () => {});
    await audio.pushPcm(new Int16Array(320));
    await audio.pushPcm(new Int16Array(17));
    assert.deepEqual(chunks, [320, 17]);
    assert.equal(timers.size, 1);
    [...timers.values()][0]();
    await new Promise(setImmediate);
    assert.equal(calls.filter((call) => call === "finish").length, 1);
    await audio.pushPcm(new Int16Array(640));
    audio.interrupt();
    assert.equal(timers.size, 0);
    assert.equal(calls.filter((call) => call === "finish").length, 1);
  } finally {
    globalThis.window = previousWindow;
  }
});
