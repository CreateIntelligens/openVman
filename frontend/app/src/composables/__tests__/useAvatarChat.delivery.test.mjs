import { decisionDebugModuleUrl } from './helpers/decisionDebugModule.mjs';
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../useAvatarChat.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
}).outputText.replace(/from ['"]\.\.\/components\/debug\/decisionDebug['"]/, `from "${decisionDebugModuleUrl}"`)
  .replace(/import \{ ref, readonly, onUnmounted \} from ['"]vue['"];?/, `
    const ref = (value) => ({ value });
    const readonly = (value) => value;
    const onUnmounted = () => {};
  `)
  .replace(/import\s*\{\s*apiFetch\s*\}\s*from\s*['"][^'"]+['"];?/, "const apiFetch = (...args) => fetch(...args);");
const { useAvatarChat } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`,
);
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

async function harness(t) {
  const requests = [], replies = [], errors = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (url, init) => new Promise((resolve, reject) => {
    requests.push({ url, init, body: JSON.parse(init.body), resolve, reject });
  });
  t.after(() => { globalThis.fetch = originalFetch; });
  const chat = useAvatarChat({
    mode: "text",
    onUtteranceComplete: (text) => replies.push(text),
    onServerError: (...args) => errors.push(args),
  });
  await chat.connect();
  const reply = (index, text = "回答") => {
    const { body } = requests[index];
    requests[index].resolve({ ok: true, json: async () => ({
      reply: text, requires_accept: true,
      turn_id: body.turn_id, turn_revision: body.turn_revision,
    }) });
  };
  return { chat, requests, replies, errors, reply };
}

test("only the newest complete answer is acknowledged and played", async (t) => {
  const { chat, requests, replies, reply } = await harness(t);
  chat.sendMessage("第一句");
  chat.sendMessage("第二句");
  assert.equal(requests[0].body.turn_id, requests[1].body.turn_id);
  assert.equal(requests[1].body.turn_revision, 2);
  reply(0, "舊回答"); await tick();
  assert.equal(requests.length, 2, "discarded replies must never acknowledge");
  reply(1, "合併回答"); await tick();
  assert.equal(requests[2].url, "/api/v1/chat/accept");
  assert.equal(requests[2].body.turn_revision, 2);
  assert.deepEqual(replies, []);
  requests[2].resolve({ ok: true }); await tick();
  assert.deepEqual(replies, ["合併回答"]);
});

test("response headers do not close the merge window before the body arrives", async (t) => {
  const { chat, requests } = await harness(t);
  let resolveBody;
  chat.sendMessage("第一句");
  requests[0].resolve({ ok: true, json: () => new Promise((resolve) => { resolveBody = resolve; }) });
  await tick();
  assert.equal(chat.mergesWithPending(), true);
  chat.sendMessage("第二句");
  resolveBody({ reply: "舊回答", requires_accept: true }); await tick();
  assert.equal(requests.length, 2);
  assert.equal(requests[1].body.message, "第一句\n第二句");
});

test("the next turn waits until the accepted previous turn is persisted", async (t) => {
  const { chat, requests, replies, reply } = await harness(t);
  chat.sendMessage("第一句");
  reply(0); await tick();
  assert.equal(chat.mergesWithPending(), false);
  chat.sendMessage("下一輪"); await tick();
  assert.equal(requests.length, 2, "next generation must await acknowledgement");
  requests[1].resolve({ ok: true }); await tick();
  assert.equal(requests.length, 3);
  assert.equal(requests[2].body.message, "下一輪");
  assert.notEqual(requests[2].body.turn_id, requests[0].body.turn_id);
  assert.deepEqual(replies, [], "superseded playback must stay stopped");
});

test("stopping an unreceived answer never acknowledges it", async (t) => {
  const { chat, requests, replies, reply } = await harness(t);
  chat.sendMessage("第一句");
  chat.interrupt();
  reply(0); await tick();
  assert.equal(requests.length, 1);
  assert.deepEqual(replies, []);
});

test("a late non-abort failure cannot put a newer request into ERROR", async (t) => {
  const { chat, requests, errors } = await harness(t);
  chat.sendMessage("第一句");
  chat.sendMessage("第二句");
  requests[0].reject(new Error("old connection failed")); await tick();
  assert.equal(chat.state.value, "THINKING");
  assert.deepEqual(errors, []);
});

test("lost acknowledgement is retried once with exactly the same turn", async (t) => {
  const { chat, requests, replies, reply } = await harness(t);
  chat.sendMessage("第一句"); reply(0); await tick();
  requests[1].reject(new TypeError("network failed")); await tick();
  assert.deepEqual(requests[1].body, requests[2].body);
  requests[2].resolve({ ok: true }); await tick();
  assert.deepEqual(replies, ["回答"]);
});

test("a rejected acknowledgement is surfaced and never played", async (t) => {
  const { chat, requests, replies, errors, reply } = await harness(t);
  chat.sendMessage("第一句"); reply(0); await tick();
  requests[1].resolve({ ok: false, status: 409 }); await tick();
  assert.equal(requests.length, 2);
  assert.equal(chat.state.value, "ERROR");
  assert.deepEqual(replies, []);
  assert.equal(errors[0][0], "BRAIN_ERROR");
});

test('decision debug is opt-in, shows actual provider, and clears on toggle and new turn', async t => {
  const { chat, requests } = await harness(t)
  assert.equal(chat.decisionDebugEnabled.value, false)
  chat.setDecisionDebug(true)
  chat.sendMessage('請直接講重點')
  assert.equal(requests[0].body.decision_debug, true)
  const diagnostic = {
    turn_id: 'turn', status: 'available', provider: 'jev', hop_id: 'jev', model: 'jev-latest',
    elapsed_ms: 35, signals: [{ id: 'tone', type: 'choice', value: 'frustrated', confidence: .95, accepted: true }],
    policy: { tone: 'frustrated' },
  }
  requests[0].resolve({ ok: true, json: async () => ({ reply: '先做這件事。', decision_debug: diagnostic }) })
  await tick()
  assert.equal(chat.decisionDebug.value.provider, 'jev')
  assert.equal(chat.decisionDebug.value.signals[0].value, 'frustrated')
  chat.sendMessage('下一題')
  assert.equal(chat.decisionDebug.value, null)
  chat.setDecisionDebug(false)
  assert.equal(chat.decisionDebug.value, null)
  assert.equal(chat.decisionDebugEnabled.value, false)
})

test('Live debug rejects late turns and clears on interruption and reconnect', async t => {
  const originalWebSocket = globalThis.WebSocket
  const originalWindow = globalThis.window
  globalThis.window = {location:{protocol:'http:',host:'test'}}
  class FakeSocket {
    static OPEN = 1
    readyState = 1
    sent = []
    constructor() { FakeSocket.last = this }
    send(text) { this.sent.push(JSON.parse(text)) }
    close() {}
    receive(data) { this.onmessage({data:JSON.stringify(data)}) }
  }
  globalThis.WebSocket = FakeSocket
  const chat = useAvatarChat({mode:'live',wsUrlBuilder:()=> 'ws://test'})
  t.after(()=>{ chat.disconnect();globalThis.WebSocket=originalWebSocket;globalThis.window=originalWindow })
  const connecting = chat.connect()
  const socket = FakeSocket.last
  socket.onopen()
  socket.receive({event:'server_init_ack',session_id:'s1'})
  await connecting
  chat.setDecisionDebug(true)
  const report={turn_id:'server:1',status:'available',provider:'clef',hop_id:'clef-primary',model:'clef-flash',elapsed_ms:40,signals:[],policy:{tone:'confused'}}
  chat.sendMessage('第一題')
  const first = socket.sent.findLast(event=>event.event==='user_speak').turn_id
  chat.sendMessage('第二題')
  const latest = socket.sent.findLast(event=>event.event==='user_speak').turn_id
  const event={event:'server_decision_debug',session_id:'s1',scope:'text',diagnostics:report}
  socket.receive({...event,client_turn_id:first})
  assert.equal(chat.decisionDebug.value,null)
  socket.receive({...event,client_turn_id:latest})
  assert.equal(chat.decisionDebug.value.policy.tone,'confused')
  chat.interrupt()
  assert.equal(chat.decisionDebug.value,null)
  socket.receive({...event,client_turn_id:latest})
  assert.equal(chat.decisionDebug.value,null)
  chat.sendMessage('第三題')
  const third = socket.sent.findLast(event=>event.event==='user_speak').turn_id
  socket.receive({...event,client_turn_id:third})
  assert.notEqual(chat.decisionDebug.value,null)
  socket.onclose()
  assert.equal(chat.decisionDebug.value,null)
})
