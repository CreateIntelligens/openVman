import { loadAvatarChat } from './helpers/avatarChatModule.mjs';
import assert from "node:assert/strict";
import { test } from "node:test";

const { useAvatarChat } = await loadAvatarChat("const apiFetch = (...args) => fetch(...args);");
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const encoder = new TextEncoder();
const sse = (event, data) => encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);

/** A /chat/stream response whose events the test pushes one at a time. */
function streamResponse() {
  let controller;
  const body = new ReadableStream({ start(c) { controller = c; } });
  const response = new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
  return {
    response,
    sentence: (index, text) => controller.enqueue(sse("sentence", { index, text })),
    done: (data) => { controller.enqueue(sse("done", data)); controller.close(); },
    error: (data) => { controller.enqueue(sse("error", data)); controller.close(); },
  };
}

async function harness(t) {
  const requests = [], events = [], errors = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (url, init) => new Promise((resolve, reject) => {
    requests.push({ url, init, body: JSON.parse(init.body), resolve, reject });
  });
  t.after(() => { globalThis.fetch = originalFetch; });
  const chat = useAvatarChat({
    mode: "text",
    chatStreamEndpoint: "/api/v1/chat/stream",
    onUtteranceComplete: (text) => events.push(["utterance", text]),
    onReplyStart: (context) => events.push(["start", context.source]),
    onReplySentence: (text) => events.push(["sentence", text]),
    onReplyEnd: (text) => events.push(["end", text]),
    onStopAudio: () => events.push(["stop"]),
    onServerError: (...args) => errors.push(args),
  });
  await chat.connect();
  const open = (index) => {
    const stream = streamResponse();
    requests[index].resolve(stream.response);
    return stream;
  };
  const accepted = (index) => requests[index].resolve({ ok: true });
  return { chat, requests, events, errors, open, accepted };
}

const doneFor = (request, extra = {}) => ({
  reply: "第一句。第二句。",
  requires_accept: true,
  turn_id: request.body.turn_id,
  turn_revision: request.body.turn_revision,
  ...extra,
});

test("sentences reach TTS as they arrive; done is accepted before the reply ends", async (t) => {
  const { chat, requests, events, open, accepted } = await harness(t);
  chat.sendMessage("營業時間？");
  assert.equal(requests[0].url, "/api/v1/chat/stream");
  const stream = open(0);
  stream.sentence(0, "第一句。"); await tick();
  assert.equal(chat.state.value, "SPEAKING");
  assert.deepEqual(events, [["start", "text"], ["sentence", "第一句。"]]);
  stream.sentence(1, "第二句。"); await tick();
  stream.done(doneFor(requests[0], { session_id: "s-1" })); await tick();
  assert.equal(requests[1].url, "/api/v1/chat/accept");
  assert.equal(events.some(([name]) => name === "end"), false, "the turn is not finished before acceptance");
  accepted(1); await tick();
  assert.equal(chat.state.value, "IDLE");
  assert.equal(chat.sessionId.value, "s-1");
  assert.deepEqual(events.slice(2), [["sentence", "第二句。"], ["end", "第一句。第二句。"]]);
  assert.equal(events.some(([name]) => name === "utterance"), false);
});

test("a deployment without the stream route falls back to /chat and stays there", async (t) => {
  const { chat, requests, events } = await harness(t);
  chat.sendMessage("你好");
  requests[0].resolve(new Response("", { status: 404 })); await tick();
  assert.equal(requests[1].url, "/api/v1/chat");
  assert.deepEqual(requests[1].body, requests[0].body);
  requests[1].resolve({ ok: true, json: async () => ({ reply: "整段回答" }) }); await tick();
  assert.deepEqual(events, [["utterance", "整段回答"]]);
  chat.sendMessage("下一題"); await tick();
  assert.equal(requests[2].url, "/api/v1/chat");
});

test("a 404 from both routes is a missing project, not a missing stream route", async (t) => {
  const { chat, requests, errors } = await harness(t);
  chat.sendMessage("你好");
  requests[0].resolve(new Response("", { status: 404 })); await tick();
  assert.equal(requests[1].url, "/api/v1/chat");
  requests[1].resolve(new Response(JSON.stringify({ error: "project not found" }), { status: 404 }));
  await tick(); await tick();
  assert.equal(errors[0][0], "BRAIN_ERROR");
  chat.sendMessage("再試一次"); await tick();
  assert.equal(requests[2].url, "/api/v1/chat/stream");
});

test("a rejected acknowledgement stops a reply that already started speaking", async (t) => {
  const { chat, requests, events, errors, open } = await harness(t);
  chat.sendMessage("你好");
  const stream = open(0);
  stream.sentence(0, "第一句。"); await tick();
  stream.done(doneFor(requests[0], { reply: "第一句。" })); await tick();
  requests[1].resolve({ ok: false, status: 409 }); await tick();
  assert.equal(chat.state.value, "ERROR");
  assert.equal(errors[0][0], "BRAIN_ERROR");
  assert.deepEqual(events.at(-1), ["stop"]);
  assert.equal(events.some(([name]) => name === "end"), false);
});

test("stopping aborts the stream and ignores sentences that were already in flight", async (t) => {
  const { chat, requests, events, open } = await harness(t);
  chat.sendMessage("講長一點");
  const stream = open(0);
  stream.sentence(0, "第一句。"); await tick();
  chat.interrupt();
  assert.equal(requests[0].init.signal.aborted, true);
  assert.deepEqual(events.at(-1), ["stop"]);
  const before = events.length;
  try { stream.sentence(1, "不該念。"); } catch { /* stream already cancelled */ }
  await tick();
  assert.equal(events.length, before);
  assert.equal(requests.length, 1, "an interrupted turn is never accepted");
});

test("input while still thinking merges; input after the first sentence is a new turn", async (t) => {
  const { chat, requests, open } = await harness(t);
  chat.sendMessage("第一句");
  assert.equal(chat.sendMessage("補充").merged, true);
  assert.equal(requests[0].init.signal.aborted, true);
  assert.equal(requests[1].body.message, "第一句\n補充");
  assert.equal(requests[1].body.turn_revision, 2);
  const stream = open(1);
  stream.sentence(0, "好的。"); await tick();
  assert.equal(chat.mergesWithPending(), false);
  assert.equal(chat.sendMessage("另一題").merged, undefined);
  assert.equal(requests[1].init.signal.aborted, true);
});

test("an error event is reported with its code and leaves the turn unaccepted", async (t) => {
  const { chat, requests, errors, open } = await harness(t);
  chat.sendMessage("你好");
  open(0).error({ status: 429, detail: { error_code: "RATE_LIMITED", message: "太快了", retry_after_ms: 2000 } });
  await tick(); await tick();
  assert.equal(chat.state.value, "ERROR");
  assert.deepEqual(errors, [["RATE_LIMITED", "太快了", 2000]]);
  assert.equal(requests.length, 1);
});

test("a stream that ends without done is an error, not a silent stop", async (t) => {
  const { chat, errors, requests } = await harness(t);
  chat.sendMessage("你好");
  const body = new ReadableStream({ start(c) { c.enqueue(sse("sentence", { index: 0, text: "一半" })); c.close(); } });
  requests[0].resolve(new Response(body, { status: 200 }));
  await tick(); await tick();
  assert.equal(chat.state.value, "ERROR");
  assert.equal(errors[0][0], "BRAIN_ERROR");
});

test("media from done is attached to the subtitle bubble already on screen", async (t) => {
  const { chat, requests, open, accepted } = await harness(t);
  chat.sendMessage("給我看產品圖");
  const stream = open(0);
  stream.sentence(0, "這是產品。"); await tick();
  chat.beginAssistantMessage();
  chat.appendAssistantText("這是產品。");
  stream.done(doneFor(requests[0], { reply: "這是產品。", image_id: "img-1", url: "https://example.test/p" }));
  await tick();
  accepted(1); await tick();
  const bubble = chat.messages.value.at(-1);
  assert.equal(bubble.role, "ai");
  assert.equal(bubble.imageId, "img-1");
  assert.equal(bubble.url, "https://example.test/p");
});
