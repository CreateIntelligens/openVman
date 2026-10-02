import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import ts from "typescript";

// 2026-10-02：虛擬人還在想時使用者補一句，兩句要一起回答，而不是只答後一句。
const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../useAvatarChat.ts"), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
}).outputText
  .replace(
    /import \{ ref, readonly, onUnmounted \} from ['"]vue['"];?/,
    [
      "const ref = (value) => ({ value });",
      "const readonly = (value) => value;",
      "const onUnmounted = () => undefined;",
    ].join("\n"),
  )
  .replace(
    /import\s*\{\s*apiFetch\s*\}\s*from\s*['"][^'"]+['"];?/,
    "const apiFetch = (url, init) => fetch(url, init);",
  );
const { useAvatarChat } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`
);

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

/** fetch 不自己回：測試決定哪個請求什麼時候回答。 */
function withPendingFetch(run) {
  return async () => {
    const previousFetch = globalThis.fetch;
    const requests = [];
    globalThis.fetch = (_url, init) => new Promise((resolveFetch, reject) => {
      const request = {
        body: JSON.parse(init.body),
        signal: init.signal,
        reply: (text) => resolveFetch({ ok: true, json: async () => ({ reply: text }) }),
      };
      requests.push(request);
      init.signal.addEventListener("abort", () => {
        reject(new DOMException("Aborted", "AbortError"));
      }, { once: true });
    });
    try {
      await run(requests);
    } finally {
      globalThis.fetch = previousFetch;
    }
  };
}

function textChat(replies = []) {
  const chat = useAvatarChat({
    mode: "text",
    chatEndpoint: "/chat",
    onUtteranceComplete: (text) => replies.push(text),
  });
  return chat;
}

test("a sentence added while thinking is merged into one request and one bubble", withPendingFetch(async (requests) => {
  const replies = [];
  const chat = textChat(replies);
  await chat.connect();

  assert.equal(chat.sendMessage("沉水泵多深？").merged, undefined);
  await tick();
  assert.equal(chat.state.value, "THINKING");
  assert.equal(chat.mergesWithPending(), true);

  const result = chat.sendMessage("還有馬力多大？", undefined, undefined, "zh");
  await tick();

  assert.deepEqual(result, { accepted: true, merged: true });
  assert.equal(requests[0].signal.aborted, true);
  assert.equal(requests.length, 2);
  assert.equal(requests[1].body.message, "沉水泵多深？\n還有馬力多大？");
  assert.deepEqual(requests[1].body.metadata, { speech_language: "zh" });
  assert.deepEqual(
    chat.messages.value.map((m) => [m.role, m.text]),
    [["user", "沉水泵多深？\n還有馬力多大？"]],
  );

  requests[1].reply("約十公尺，五馬力。");
  await tick();
  assert.deepEqual(replies, ["約十公尺，五馬力。"]);
  assert.equal(chat.state.value, "IDLE");
}));

test("three sentences while thinking all end up in the same request", withPendingFetch(async (requests) => {
  const chat = textChat();
  await chat.connect();
  chat.sendMessage("一");
  chat.sendMessage("二");
  chat.sendMessage("三");
  await tick();
  assert.equal(requests.at(-1).body.message, "一\n二\n三");
  assert.equal(chat.messages.value.length, 1);
}));

test("once the reply has arrived the next sentence is a new turn", withPendingFetch(async (requests) => {
  const chat = textChat();
  await chat.connect();
  chat.sendMessage("沉水泵多深？");
  await tick();
  requests[0].reply("約十公尺。");
  await tick();

  assert.equal(chat.mergesWithPending(), false);
  const result = chat.sendMessage("那馬力呢？");
  await tick();

  assert.equal(result.merged, undefined);
  assert.equal(requests[1].body.message, "那馬力呢？");
  assert.deepEqual(
    chat.messages.value.filter((m) => m.role === "user").map((m) => m.text),
    ["沉水泵多深？", "那馬力呢？"],
  );
}));

test("stopping the answer means the next sentence starts over", withPendingFetch(async (requests) => {
  const chat = textChat();
  await chat.connect();
  chat.sendMessage("沉水泵多深？");
  await tick();
  chat.interrupt();
  chat.sendMessage("算了，營業時間？");
  await tick();
  assert.equal(requests[1].body.message, "算了，營業時間？");
}));

test("quick questions carry their own source and are never merged", withPendingFetch(async (requests) => {
  const chat = textChat();
  await chat.connect();
  chat.sendMessage("沉水泵多深？");
  await tick();
  assert.equal(chat.mergesWithPending("qa/pump.md"), false);
  chat.sendMessage("營業時間？", "qa/hours.md", "九點到六點");
  await tick();
  assert.equal(requests[1].body.message, "營業時間？");

  // 反過來：等的是快速問答，使用者再講一句也不接在它後面。
  assert.equal(chat.mergesWithPending(), false);
}));
