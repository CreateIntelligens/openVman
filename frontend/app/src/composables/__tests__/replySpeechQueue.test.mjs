import assert from "node:assert/strict";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { build } from "esbuild";

const __dirname = dirname(fileURLToPath(import.meta.url));
const { outputFiles } = await build({
  entryPoints: [resolve(__dirname, "../replySpeechQueue.ts")],
  bundle: true, write: false, platform: "node", format: "esm", logLevel: "error",
});
const { createReplySpeechQueue } = await import(
  `data:text/javascript;base64,${Buffer.from(outputFiles[0].text).toString("base64")}`
);

function harness() {
  const spoken = [];
  const finishers = [];
  const queue = createReplySpeechQueue({
    speak: (text) => new Promise((resolve) => {
      spoken.push(text);
      finishers.push(resolve);
    }),
  });
  const finishCurrent = async () => {
    finishers.shift()?.();
    await new Promise((r) => setTimeout(r, 0));
  };
  return { queue, spoken, finishCurrent };
}

test("the first sentence goes to TTS at once; later ones wait for it", async () => {
  const { queue, spoken, finishCurrent } = harness();
  queue.push("第一句。");
  assert.deepEqual(spoken, ["第一句。"]);
  queue.push("第二句。");
  assert.deepEqual(spoken, ["第一句。"], "only one TTS request at a time keeps audio in order");
  await finishCurrent();
  assert.deepEqual(spoken, ["第一句。", "第二句。"]);
});

test("sentences that arrive during one request are spoken together, whitespace kept", async () => {
  const { queue, spoken, finishCurrent } = harness();
  queue.push("好的。");
  queue.push("\n營業時間是九點。");
  queue.push("週日公休。");
  await finishCurrent();
  assert.deepEqual(spoken, ["好的。", "\n營業時間是九點。週日公休。"]);
  await finishCurrent();
  await queue.idle();
});

test("cancel drops queued sentences and a new reply starts fresh", async () => {
  const { queue, spoken, finishCurrent } = harness();
  queue.push("舊的一句。");
  queue.push("舊的第二句。");
  queue.cancel();
  queue.push("新回答。");
  assert.deepEqual(spoken, ["舊的一句。", "新回答。"]);
  await finishCurrent();
  await finishCurrent();
  assert.deepEqual(spoken, ["舊的一句。", "新回答。"], "the cancelled reply never resumes");
});

test("a failed segment does not stop the following sentences", async () => {
  const spoken = [];
  const queue = createReplySpeechQueue({
    speak: async (text) => {
      spoken.push(text);
      if (text === "壞掉。") throw new Error("tts failed");
    },
  });
  queue.push("壞掉。");
  queue.push("下一句。");
  await queue.idle();
  assert.deepEqual(spoken, ["壞掉。", "下一句。"]);
});
