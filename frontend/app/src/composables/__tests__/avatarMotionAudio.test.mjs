import assert from "node:assert/strict";
import { test } from "node:test";
import { build } from "esbuild";

const { outputFiles } = await build({
  entryPoints: [new URL("../avatarMotionAudio.ts", import.meta.url).pathname],
  bundle: true, write: false, platform: "node", format: "esm", logLevel: "error",
});
const { createAvatarMotionAudioGate, resolveAvatarMotionIntent } = await import(
  `data:text/javascript;base64,${Buffer.from(outputFiles[0].text).toString("base64")}`,
);
const deferred = () => {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
};
const flush = () => new Promise((done) => setImmediate(done));

test("actual or preparing speech wins over thinking; TTS wait remains thinking", () => {
  const idle = { playing: false, preparing: false, thinking: false, ttsPending: false };
  assert.equal(resolveAvatarMotionIntent(idle), "idle");
  assert.equal(resolveAvatarMotionIntent({ ...idle, ttsPending: true }), "thinking");
  assert.equal(resolveAvatarMotionIntent({ ...idle, thinking: true }), "thinking");
  assert.equal(resolveAvatarMotionIntent({ ...idle, thinking: true, playing: true }), "speaking");
  assert.equal(resolveAvatarMotionIntent({ ...idle, thinking: true, preparing: true }), "speaking");
});

test("first PCM waits for the visual handoff and concurrent chunks keep arrival order", async () => {
  const ready = deferred(), scheduled = deferred(), played = [], pending = [];
  let preparations = 0;
  const gate = createAvatarMotionAudioGate({ enabled: () => true, playing: () => false,
    prepare: () => { preparations += 1; return ready.promise; },
    play: async (data) => { played.push(data); await scheduled.promise; },
    onPreparing: (value) => pending.push(value), onError: assert.fail });
  const first = gate.play(1), second = gate.play(2);
  await flush();
  assert.deepEqual(played, []);
  assert.equal(preparations, 1);
  ready.resolve();
  await flush();
  assert.deepEqual(played, [1, 2]);
  assert.equal(pending.at(-1), true, "schedule 完成前保留說話意圖");
  scheduled.resolve();
  await Promise.all([first, second]);
  assert.equal(pending.at(-1), false);
});

test("stopping while a handoff is pending drops stale PCM without disturbing a new turn", async () => {
  const old = deferred(), next = deferred(), played = [], pending = [];
  let generation = 0;
  const gate = createAvatarMotionAudioGate({ enabled: () => true, playing: () => false,
    prepare: () => (++generation === 1 ? old.promise : next.promise),
    play: async (data) => { played.push(data); },
    onPreparing: (value) => pending.push(value), onError: assert.fail });
  const stale = gate.play("old");
  gate.cancel();
  const current = gate.play("new");
  old.resolve();
  await stale;
  assert.deepEqual(played, []);
  assert.equal(pending.at(-1), true);
  next.resolve();
  await current;
  assert.deepEqual(played, ["new"]);
  assert.equal(pending.at(-1), false);
});

test("ordinary avatars and an already-playing stream schedule without a new handoff", async () => {
  for (const [enabled, playing] of [[false, false], [true, true]]) {
    const played = [];
    const gate = createAvatarMotionAudioGate({ enabled: () => enabled, playing: () => playing,
      prepare: () => assert.fail("不該重做切換"), play: async (data) => { played.push(data); },
      onPreparing: () => assert.fail("不該進入準備狀態"), onError: assert.fail });
    await gate.play("pcm");
    assert.deepEqual(played, ["pcm"]);
  }
});

test("a motion error is reported and does not discard the answer's audio", async () => {
  const errors = [], played = [];
  const gate = createAvatarMotionAudioGate({ enabled: () => true, playing: () => false,
    prepare: async () => { throw new Error("decoder unavailable"); },
    play: async (data) => { played.push(data); }, onPreparing() {},
    onError: (error) => errors.push(error.message) });
  await gate.play("pcm");
  assert.deepEqual(errors, ["decoder unavailable"]);
  assert.deepEqual(played, ["pcm"]);
});
