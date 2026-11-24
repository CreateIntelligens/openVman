import assert from "node:assert/strict";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { build } from "esbuild";

const __dirname = dirname(fileURLToPath(import.meta.url));
const { outputFiles } = await build({
  entryPoints: [resolve(__dirname, "../replySpeech.ts")],
  bundle: true, write: false, platform: "node", format: "esm", logLevel: "error",
});
const { createReplySpeech } = await import(
  `data:text/javascript;base64,${Buffer.from(outputFiles[0].text).toString("base64")}`
);

function harness(speak = async () => {}) {
  const spoken = [];
  const waiting = [];
  const reply = createReplySpeech({
    speak: (text) => {
      spoken.push(text);
      return speak(text);
    },
    onWaiting: (value) => waiting.push(value),
  });
  return { reply, spoken, waiting };
}

test("streamed sentences are not spoken until the reply is complete", () => {
  const { reply, spoken, waiting } = harness();
  reply.collect("第一句。");
  reply.collect("第二句。");
  assert.deepEqual(spoken, [], "no TTS request before the reply is complete");
  assert.equal(waiting.at(-1), true, "the avatar is about to speak, so the mic stays closed");
  reply.finish("第一句。第二句。");
  assert.deepEqual(spoken, ["第一句。第二句。"], "one TTS request for the whole reply");
});

test("the final reply is spoken, not sentences the model took back", () => {
  const { reply, spoken } = harness();
  reply.collect("先寫的。");
  reply.collect("收回的。");
  reply.finish("最後的回答。");
  assert.deepEqual(spoken, ["最後的回答。"]);
});

test("an empty final reply falls back to the collected sentences, whitespace kept", () => {
  const { reply, spoken } = harness();
  reply.collect("好的。");
  reply.collect("\n營業時間是九點。");
  reply.finish("  ");
  assert.deepEqual(spoken, ["好的。\n營業時間是九點。"]);
});

test("nothing to say clears the waiting state instead of leaving the mic closed", () => {
  const { reply, spoken, waiting } = harness();
  reply.collect("   ");
  reply.finish("");
  assert.deepEqual(spoken, []);
  assert.equal(waiting.at(-1), false);
});

test("cancel drops collected sentences and clears the waiting state", () => {
  const { reply, spoken, waiting } = harness();
  reply.collect("舊的一句。");
  reply.cancel();
  assert.equal(waiting.at(-1), false);
  reply.finish("");
  assert.deepEqual(spoken, [], "the cancelled reply is never spoken");
  reply.speak("新回答。");
  assert.deepEqual(spoken, ["新回答。"]);
});

test("a failed TTS request still lets idle resolve", async () => {
  const { reply, spoken } = harness(async () => {
    throw new Error("tts failed");
  });
  reply.speak("壞掉。");
  await reply.idle();
  assert.deepEqual(spoken, ["壞掉。"]);
});

test("a cancelled reply that settles late does not clear the next reply's waiting state", async () => {
  // PR Agent 回報的競態：舊回合的 TTS 被打斷後才結束，不能把新回合的 ttsPending 清成 false。
  const finishers = [];
  const { reply, waiting } = harness(() => new Promise((resolve) => finishers.push(resolve)));
  reply.speak("舊回答。");
  assert.equal(waiting.at(-1), true, "speaking keeps the mic closed");
  reply.cancel();
  reply.collect("新回答的第一句。");
  assert.equal(waiting.at(-1), true);
  finishers[0]();
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(waiting.at(-1), true, "the old reply settling late leaves the new reply waiting");
  reply.finish("新回答的第一句。");
  finishers[1]();
  await reply.idle();
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(waiting.at(-1), false, "the current reply ending clears it");
});

test("speaking twice without cancel lets only the latest reply clear the state", async () => {
  const finishers = [];
  const { reply, waiting } = harness(() => new Promise((resolve) => finishers.push(resolve)));
  reply.speak("第一段。");
  reply.speak("第二段。");
  finishers[0]();
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(waiting.at(-1), true);
  finishers[1]();
  await reply.idle();
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(waiting.at(-1), false);
});
