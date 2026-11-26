import { loadAvatarChat } from './helpers/avatarChatModule.mjs';
import assert from "node:assert/strict";
import { test } from "node:test";

const { useAvatarChat } = await loadAvatarChat("const apiFetch = (...args) => fetch(...args);");
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

function captureChatBodies(t, language) {
  const bodies = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    bodies.push({ url, body: JSON.parse(init.body) });
    return new Response(JSON.stringify({ reply: "ok", session_id: "s" }), {
      status: 200, headers: { "Content-Type": "application/json" },
    });
  };
  t.after(() => { globalThis.fetch = originalFetch; });
  const chat = useAvatarChat({ mode: "text", ...(language ? { language } : {}) });
  return { chat, bodies };
}

test("a locked language is sent with every text chat request and read per request", async (t) => {
  let current = "es";
  const { chat, bodies } = captureChatBodies(t, () => current);
  await chat.connect();

  chat.sendMessage("hola"); await tick();
  current = "ja";
  chat.sendMessage("こんにちは"); await tick();

  assert.deepEqual(bodies.map(({ body }) => body.language), ["es", "ja"]);
});

test("no language option or an empty one leaves the request without a language field", async (t) => {
  for (const language of [undefined, () => ""]) {
    const { chat, bodies } = captureChatBodies(t, language);
    await chat.connect();
    chat.sendMessage("你好"); await tick();
    assert.equal("language" in bodies[0].body, false);
  }
});

test("the stream endpoint carries the language too", async (t) => {
  const bodies = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    bodies.push({ url, body: JSON.parse(init.body) });
    return new Response("", { status: 404 });
  };
  t.after(() => { globalThis.fetch = originalFetch; });
  const chat = useAvatarChat({
    mode: "text", chatStreamEndpoint: "/api/v1/chat/stream", language: () => "en",
  });
  await chat.connect();
  chat.sendMessage("hello"); await tick(); await tick();

  assert.equal(bodies[0].url, "/api/v1/chat/stream");
  assert.equal(bodies[0].body.language, "en");
});

async function liveInitCapabilities(t, language) {
  const originalWebSocket = globalThis.WebSocket;
  const originalWindow = globalThis.window;
  globalThis.window = { location: { protocol: "http:", host: "test" } };
  class FakeSocket {
    static OPEN = 1;
    readyState = 1;
    sent = [];
    constructor() { FakeSocket.last = this; }
    send(text) { this.sent.push(JSON.parse(text)); }
    close() {}
    receive(data) { this.onmessage({ data: JSON.stringify(data) }); }
  }
  globalThis.WebSocket = FakeSocket;
  const chat = useAvatarChat({ mode: "live", wsUrlBuilder: () => "ws://test", ...(language ? { language } : {}) });
  t.after(() => { chat.disconnect(); globalThis.WebSocket = originalWebSocket; globalThis.window = originalWindow; });
  const connecting = chat.connect();
  const socket = FakeSocket.last;
  socket.onopen();
  socket.receive({ event: "server_init_ack", session_id: "s1" });
  await connecting;
  return socket.sent.find((event) => event.event === "client_init").capabilities;
}

test("live mode announces the locked language in client_init capabilities", async (t) => {
  const capabilities = await liveInitCapabilities(t, () => "es");
  assert.equal(capabilities.language, "es");
});

test("live mode without a language sends no language capability", async (t) => {
  const capabilities = await liveInitCapabilities(t, undefined);
  assert.equal("language" in capabilities, false);
});

test("a greeting played locally is stopped by the next question, the stop button and only once", async (t) => {
  let stops = 0;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ reply: "ok", session_id: "s" }), {
    status: 200, headers: { "Content-Type": "application/json" },
  });
  t.after(() => { globalThis.fetch = originalFetch; });
  const chat = useAvatarChat({ mode: "text", onStopAudio: () => { stops += 1; } });
  await chat.connect();

  // 開場白還在播時送出問題：沒播完的字幕不能接到下一則泡泡，要先停掉。
  chat.beginLocalPlayback();
  chat.sendMessage("RHINO 最大流量？"); await tick();
  assert.equal(stops, 1);

  chat.beginLocalPlayback();
  chat.interrupt();
  assert.equal(stops, 2);
});
