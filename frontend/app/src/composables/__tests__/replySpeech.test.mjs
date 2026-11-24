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
