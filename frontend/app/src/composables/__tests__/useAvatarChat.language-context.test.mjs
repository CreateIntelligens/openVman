import { decisionDebugModuleUrl } from './helpers/decisionDebugModule.mjs';
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

async function loadComposable(file, replacements) {
  let compiled = ts.transpileModule(
    readFileSync(new URL(file, import.meta.url), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 } },
  ).outputText.replace(/from ['"]\.\.\/components\/debug\/decisionDebug['"]/, `from "${decisionDebugModuleUrl}"`);
  for (const [pattern, replacement] of replacements) {
    compiled = compiled.replace(pattern, replacement);
  }
  return import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
}

const vueStubs = `
  const ref = (value) => ({ value });
  const readonly = (value) => value;
  const onUnmounted = () => {};
  const computed = (get) => ({ get value() { return get(); } });
  const watch = () => {};
`;
const { useAvatarChat } = await loadComposable("../useAvatarChat.ts", [
  [/import.*from ['"]vue['"];?/, vueStubs],
  [/import.*from ['"]\.\.\/api\/http['"];?/, "const apiFetch = (...args) => fetch(...args);"],
]);
const { useLanguageRoutes } = await loadComposable("../useLanguageRoutes.ts", [
  [/import.*from ['"]vue['"];?/, vueStubs],
  [/import.*from ['"]\.\.\/api\/http['"];?/, "const apiFetch = (...args) => fetch(...args); const parseJson = (r) => r.json();"],
  [/import.*from ['"]\.\.\/utils\/storageUtils['"];?/, "const STORAGE_KEYS = {}; const readPref = (_, fallback) => fallback; const writePref = () => {};"],
]);

const settle = () => new Promise((resolve) => setImmediate(resolve));

function harness(t) {
  const previousFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = previousFetch; });
  const requests = [];
  const replies = [];
  globalThis.fetch = (url, init) => new Promise((resolve) => {
    requests.push({ url, init, resolve });
  });
  const routes = useLanguageRoutes(() => "test-project");
  routes.available.value = ["zh", "nan"];
  const chat = useAvatarChat({
    mode: "text",
    onUtteranceComplete: (text, context) => replies.push({
      text,
      context,
      tts: routes.ttsProviderFor("gemini-tts", context.speechLanguage),
    }),
  });
  const respond = (index, reply) => {
    requests[index].resolve({ ok: true, json: async () => ({ reply }) });
    return settle();
  };
  return { chat, routes, requests, replies, respond };
}

test("Taiwanese, independent visual reply, Mandarin and typed replies keep their own language", async (t) => {
  const { chat, requests, replies, respond } = harness(t);
  await chat.connect();
  chat.sendMessage("台語問題", undefined, undefined, "nan");
  await respond(0, "台語回答");
  chat.sendVisualInput("frame", "image/jpeg", 1);
  await respond(1, "視覺回答");
  chat.sendMessage("華語問題", undefined, undefined, "zh");
  await respond(2, "華語回答");
  chat.sendMessage("快速問答");
  await respond(3, "快速回答");

  assert.deepEqual(replies.map(({ context }) => context), [
    { source: "text", speechLanguage: "nan" },
    { source: "visual", speechLanguage: null },
    { source: "text", speechLanguage: "zh" },
    { source: "text", speechLanguage: null },
  ]);
  assert.deepEqual(replies.map(({ tts }) => tts), [
    { provider: "voxcpm", switched: true },
    { provider: "gemini-tts", switched: false },
    { provider: "gemini-tts", switched: false },
    { provider: "gemini-tts", switched: false },
  ]);
  assert.equal(JSON.parse(requests[0].init.body).metadata.speech_language, "nan");
  assert.equal(JSON.parse(requests[2].init.body).metadata.speech_language, "zh");
});

test("two rapid requests discard a late Taiwanese response without changing Mandarin TTS", async (t) => {
  const { chat, requests, replies, respond } = harness(t);
  await chat.connect();
  chat.sendMessage("舊問題", undefined, undefined, "nan");
  chat.sendMessage("新問題", undefined, undefined, "zh");
  assert.equal(requests[0].init.signal.aborted, true);
  await respond(1, "最新回答");
  // 模擬即使忽略 AbortSignal、舊請求仍然送回資料的 transport。
  await respond(0, "不應播放");
  assert.deepEqual(replies, [{
    text: "最新回答",
    context: { source: "text", speechLanguage: "zh" },
    tts: { provider: "gemini-tts", switched: false },
  }]);
});

test("a response superseded while parsing JSON cannot publish its language", async (t) => {
  const { chat, requests, replies, respond } = harness(t);
  await chat.connect();
  chat.sendMessage("舊台語", undefined, undefined, "nan");
  let finishJson;
  requests[0].resolve({ ok: true, json: () => new Promise((resolve) => { finishJson = resolve; }) });
  await settle();
  chat.sendMessage("新的快速問答");
  await respond(1, "最新回答");
  finishJson({ reply: "不應播放" });
  await settle();
  assert.equal(replies.length, 1);
  assert.deepEqual(replies[0].context, { source: "text", speechLanguage: null });
  assert.equal(replies[0].tts.provider, "gemini-tts");
});
