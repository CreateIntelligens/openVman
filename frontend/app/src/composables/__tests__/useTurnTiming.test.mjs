import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { build } from "esbuild";

// 真的跑 useTurnTiming：時間點與分段對不對，只看原始碼看不出來。
const __dirname = dirname(fileURLToPath(import.meta.url));
const appRoot = resolve(__dirname, "../../..");
const { outputFiles } = await build({
  entryPoints: [resolve(appRoot, "src/composables/useTurnTiming.ts")],
  bundle: true,
  write: false,
  platform: "node",
  format: "esm",
  alias: { "@shared": resolve(appRoot, "../shared") },
  external: ["@ricky0123/vad-web"],
  logLevel: "error",
});
const { useTurnTiming, turnDurations } = await import(
  `data:text/javascript;base64,${Buffer.from(outputFiles[0].text).toString("base64")}`
);

function harness() {
  let clock = 0;
  const sent = [];
  const timing = useTurnTiming({
    now: () => clock,
    wallClock: () => Date.parse("2026-09-29T04:00:10.000Z") + clock,
    send: (payload) => sent.push(payload),
    context: () => ({
      project_id: "proj-x", session_id: "s1", voice_mode: "text",
      asr_engine: "breeze", tts_provider: "voxcpm", tts_voice: "v1",
    }),
  });
  return { timing, sent, at: (ms) => { clock = ms; } };
}

test("a voice turn reports every mark and the total from speech end to playback", () => {
  const { timing, sent, at } = harness();
  at(1000); timing.speechStarted();
  at(2800); timing.speechEnded();
  at(4100); timing.asrDone();
  timing.begin();
  at(4150); timing.mark("sent");
  at(6000); timing.mark("reply_done"); timing.replyText("您好，網球肘要避免提重物。"); timing.mark("tts_start");
  at(6900); timing.mark("first_audio");
  at(6950); timing.mark("first_audio");
  at(7000); timing.playbackStarted();

  assert.equal(sent.length, 1);
  const [turn] = sent;
  assert.equal(turn.input, "voice");
  assert.equal(turn.outcome, "played");
  assert.deepEqual(turn.marks_ms, {
    speech_start: 0, speech_end: 1800, asr_done: 3100, sent: 3150,
    reply_done: 5000, tts_start: 5000, first_audio: 5900, playback_start: 6000,
  });
  assert.deepEqual(turn.durations_ms, {
    speech: 1800, asr: 1300, send: 50, brain: 1850, tts_first_audio: 900, to_playback: 100, total: 4200,
  });
  assert.equal(turn.started_at, "2026-09-29T04:00:11.000Z");
  assert.equal(turn.reply_chars, 13);
  assert.equal(turn.asr_engine, "breeze");
});

test("a typed turn is measured from sending", () => {
  const { timing, sent, at } = harness();
  at(0); timing.begin(); timing.mark("sent");
  at(2500); timing.playbackStarted();
  assert.equal(sent[0].input, "text");
  assert.equal(sent[0].durations_ms.total, 2500);
});

test("a stop notice that arrives after the next turn began does not end it", () => {
  const { timing, sent, at } = harness();
  at(0); timing.begin(); timing.mark("sent");
  timing.interrupted();
  assert.equal(sent.length, 0);
  at(100); timing.mark("reply_done");
  timing.interrupted();
  assert.equal(sent[0].outcome, "interrupted");
});

test("a new turn before playback reports the old one as superseded", () => {
  const { timing, sent, at } = harness();
  at(0); timing.begin(); timing.mark("sent");
  at(500); timing.begin();
  assert.equal(sent[0].outcome, "superseded");
  at(900); timing.playbackStarted();
  assert.equal(sent[1].outcome, "played");
});

test("a sentence added while thinking reports the old turn as merged", () => {
  const { timing, sent, at } = harness();
  at(0); timing.begin(); timing.mark("sent");
  at(1500); timing.begin("merged");
  assert.equal(sent[0].outcome, "merged");
  at(4000); timing.playbackStarted();
  assert.equal(sent[1].outcome, "played");
});

test("every outcome the app reports is one the backend accepts", () => {
  // 後端用 Literal 驗證，前台多一種 outcome 後端會整筆 422 丟掉，量測就靜靜少了。
  const front = readFileSync(resolve(appRoot, "src/composables/useTurnTiming.ts"), "utf8");
  const back = readFileSync(resolve(appRoot, "../../backend/app/turn_timing.py"), "utf8");
  const quoted = (text) => [...text.matchAll(/['"](\w+)['"]/g)].map((m) => m[1]).sort();
  const frontUnion = front.match(/export type TurnOutcome =([^\n]*)/)[1];
  const backLiteral = back.match(/outcome: Literal\[([^\]]*)\]/)[1];
  assert.ok(quoted(frontUnion).includes("merged"));
  assert.deepEqual(quoted(frontUnion), quoted(backLiteral));
});

test("playback with no turn in flight sends nothing", () => {
  const { timing, sent } = harness();
  timing.playbackStarted();
  timing.finish("error");
  assert.equal(sent.length, 0);
  assert.deepEqual(turnDurations({}), {});
});
