import assert from "node:assert/strict";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { build } from "esbuild";

const __dirname = dirname(fileURLToPath(import.meta.url));
const { outputFiles } = await build({
  entryPoints: [resolve(__dirname, "../chatSseStream.ts")],
  bundle: true, write: false, platform: "node", format: "esm", logLevel: "error",
});
const { parseSseBlock, readSseEvents } = await import(
  `data:text/javascript;base64,${Buffer.from(outputFiles[0].text).toString("base64")}`
);

function bodyFrom(chunks) {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(typeof chunk === "string" ? encoder.encode(chunk) : chunk);
      controller.close();
    },
  });
}

async function collect(body) {
  const events = [];
  for await (const event of readSseEvents(body)) events.push(event);
  return events;
}

test("a block yields its event name and parsed JSON data", () => {
  assert.deepEqual(
    parseSseBlock('event: sentence\ndata: {"index":0,"text":"你好。"}'),
    { event: "sentence", data: { index: 0, text: "你好。" } },
  );
  assert.equal(parseSseBlock(": keep-alive"), null);
  assert.deepEqual(parseSseBlock("data: plain"), { event: "message", data: "plain" });
});

test("events split across network chunks are reassembled in order", async () => {
  const stream = 'event: sentence\ndata: {"index":0,"text":"第一句。"}\n\n'
    + 'event: sentence\ndata: {"index":1,"text":"\\n第二句。"}\n\n'
    + 'event: done\ndata: {"reply":"第一句。\\n第二句。"}\n\n';
  // 每 7 個 byte 切一刀：中文字的 UTF-8 一定會被切開。
  const bytes = new TextEncoder().encode(stream);
  const chunks = [];
  for (let i = 0; i < bytes.length; i += 7) chunks.push(bytes.slice(i, i + 7));
  const events = await collect(bodyFrom(chunks));
  assert.deepEqual(events.map((e) => e.event), ["sentence", "sentence", "done"]);
  const joined = events.filter((e) => e.event === "sentence").map((e) => e.data.text).join("");
  assert.equal(joined, events[2].data.reply);
});

test("CRLF line endings, comments and a final block without a blank line", async () => {
  const events = await collect(bodyFrom([
    ": ping\r\n\r\nevent: error\r\ndata: {\"status\":502,\"detail\":\"上游失敗\"}\r\n\r\n",
    "event: done\ndata: {\"reply\":\"x\"}",
  ]));
  assert.deepEqual(events, [
    { event: "error", data: { status: 502, detail: "上游失敗" } },
    { event: "done", data: { reply: "x" } },
  ]);
});
