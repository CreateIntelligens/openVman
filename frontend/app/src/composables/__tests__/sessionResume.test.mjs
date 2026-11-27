import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { build } from "esbuild";

import { loadAvatarChat } from "./helpers/avatarChatModule.mjs";

const { outputFiles } = await build({
  entryPoints: [fileURLToPath(new URL("../sessionResume.ts", import.meta.url))],
  bundle: true, write: false, platform: "node", format: "esm",
});
const { saveResumeSession, takeResumeSession, RESUME_WINDOW_MS } = await import(
  `data:text/javascript;base64,${Buffer.from(outputFiles[0].text).toString("base64")}`
);
const { useAvatarChat } = await loadAvatarChat("const apiFetch = (...args) => fetch(...args);");
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

function memoryStorage() {
  const data = new Map();
  return {
    data,
    getItem: (key) => (data.has(key) ? data.get(key) : null),
    setItem: (key, value) => data.set(key, String(value)),
    removeItem: (key) => data.delete(key),
  };
}

test("a saved conversation comes back once, within ten minutes, for the same project and persona", () => {
  const storage = memoryStorage();
  let now = 1_000;
  const clock = { now: () => now, storage };
  saveResumeSession({ conversationId: "c1", userId: "u1", projectId: "p", personaId: "kiosk" }, clock);
  now += RESUME_WINDOW_MS;
  assert.equal(takeResumeSession("u1", "p", "kiosk", clock), "c1");
  assert.equal(takeResumeSession("u1", "p", "kiosk", clock), null, "taken only once");
});

test("an old, mismatched, empty or unreadable entry starts a new conversation", () => {
  const base = { conversationId: "c1", userId: "u1", projectId: "p", personaId: "a" };
  const cases = [
    { save: base, later: RESUME_WINDOW_MS + 1, take: ["u1", "p", "a"] },
    { save: base, later: 0, take: ["u2", "p", "a"] },
    { save: base, later: 0, take: ["", "p", "a"] },
    { save: base, later: 0, take: ["u1", "other", "a"] },
    { save: base, later: 0, take: ["u1", "p", "other"] },
    { save: { ...base, conversationId: "" }, later: 0, take: ["u1", "p", "a"] },
    { save: { ...base, userId: "" }, later: 0, take: ["", "p", "a"] },
  ];
  for (const { save, later, take } of cases) {
    const storage = memoryStorage();
    let now = 5_000;
    saveResumeSession(save, { now: () => now, storage });
    now += later;
    assert.equal(takeResumeSession(...take, { now: () => now, storage }), null);
    assert.equal(storage.data.size, 0, "the entry is cleared either way");
  }
  const broken = memoryStorage();
  broken.setItem("openvman.avatar.resume_session", "{not json");
  assert.equal(takeResumeSession("u1", "p", "a", { storage: broken }), null);
  const throwing = { getItem() { throw new Error("denied"); }, setItem() { throw new Error("denied"); }, removeItem() {} };
  assert.doesNotThrow(() => saveResumeSession({ ...base, conversationId: "c" }, { storage: throwing }));
  assert.equal(takeResumeSession("u1", "p", "a", { storage: throwing }), null);
});

function liveChat(t) {
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
  const chat = useAvatarChat({ mode: "live", wsUrlBuilder: () => "ws://test" });
  t.after(() => { chat.disconnect(); globalThis.WebSocket = originalWebSocket; globalThis.window = originalWindow; });
  return { chat, FakeSocket };
}

test("live mode asks the gateway to continue the saved conversation and reports it as the conversation id", async (t) => {
  const { chat, FakeSocket } = liveChat(t);
  chat.resumeConversation("old-conversation", Date.now() + 60_000);
  const connecting = chat.connect();
  const socket = FakeSocket.last;
  socket.onopen();
  assert.equal(socket.sent[0].event, "client_init");
  assert.equal(socket.sent[0].capabilities.session_id, "old-conversation");
  socket.receive({ event: "server_init_ack", session_id: "new-ws-session" });
  await connecting;
  assert.equal(chat.sessionId.value, "new-ws-session");
  assert.equal(chat.conversationId(), "old-conversation");
});

test("live mode without a saved conversation sends no session id and uses the gateway session", async (t) => {
  const { chat, FakeSocket } = liveChat(t);
  const connecting = chat.connect();
  const socket = FakeSocket.last;
  socket.onopen();
  assert.equal("session_id" in socket.sent[0].capabilities, false);
  socket.receive({ event: "server_init_ack", session_id: "ws-1" });
  await connecting;
  assert.equal(chat.conversationId(), "ws-1");
});

test("text mode continues the saved conversation id in its chat requests", async (t) => {
  const bodies = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    bodies.push(JSON.parse(init.body));
    return new Response(JSON.stringify({ reply: "ok", session_id: "old-conversation" }), {
      status: 200, headers: { "Content-Type": "application/json" },
    });
  };
  t.after(() => { globalThis.fetch = originalFetch; });
  const chat = useAvatarChat({ mode: "text" });
  chat.resumeConversation("old-conversation", Date.now() + 60_000);
  await chat.connect();
  assert.equal(chat.conversationId(), "old-conversation");
  chat.sendMessage("還在嗎"); await tick();
  assert.equal(bodies[0].session_id, "old-conversation");
});

async function connectLive(chat, FakeSocket, ack) {
  const connecting = chat.connect();
  const socket = FakeSocket.last;
  socket.onopen();
  const init = socket.sent.at(-1);
  socket.receive({ event: "server_init_ack", session_id: ack });
  await connecting;
  return { socket, init };
}

test("a saved conversation is dropped once it expires, or on disconnect, project or persona change", async (t) => {
  for (const drop of [
    (chat) => chat.resumeConversation("old", Date.now() - 1),
    (chat) => { chat.resumeConversation("old", Date.now() + 60_000); chat.disconnect(); },
    (chat) => { chat.resumeConversation("old", Date.now() + 60_000); chat.setProject("other"); },
    (chat) => { chat.resumeConversation("old", Date.now() + 60_000); chat.setPersona("other"); },
  ]) {
    const { chat, FakeSocket } = liveChat(t);
    drop(chat);
    const { init } = await connectLive(chat, FakeSocket, "fresh-ws");
    assert.equal("session_id" in init.capabilities, false);
    assert.equal(chat.conversationId(), "fresh-ws");
  }
});

test("a re-init on the same socket keeps the resumed conversation id; a new socket starts over", async (t) => {
  const { chat, FakeSocket } = liveChat(t);
  chat.resumeConversation("old-conversation", Date.now() + 60_000);
  const { socket } = await connectLive(chat, FakeSocket, "ws-1");
  chat.reinit("default");
  socket.receive({ event: "server_init_ack", session_id: "ws-1b" });
  assert.equal(chat.conversationId(), "old-conversation");
  chat.disconnect();
  await connectLive(chat, FakeSocket, "ws-2");
  assert.equal(chat.conversationId(), "ws-2");
});
