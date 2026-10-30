import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import ts from "typescript";

const __dirname = dirname(fileURLToPath(import.meta.url));
const sharedSource = readFileSync(resolve(__dirname, "../../../../shared/speech/tts/pcm-stream.ts"), "utf8");
const sharedCompiled = ts.transpileModule(sharedSource, {
  compilerOptions: {
    module: ts.ModuleKind.ES2022,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText;
const sharedUrl = `data:text/javascript;base64,${Buffer.from(sharedCompiled).toString("base64")}`;

const source = readFileSync(resolve(__dirname, "../useTtsStreamer.ts"), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ES2022,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText.replace(
  /import\s*\{\s*apiFetch\s*\}\s*from\s*['"][^'"]+['"];?/,
  "const apiFetch = (url, init) => fetch(url, { ...init, credentials: 'include' });",
).replace(
  /from\s*['"]@shared\/speech['"];?/,
  `from "${sharedUrl}";`,
);

const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`;
const { useTtsStreamer, ttsResponseTimeoutMs, TtsTimeoutError } = await import(moduleUrl);

function hangingFetch() {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = (_url, init) => new Promise((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () => {
      reject(new DOMException("The operation was aborted.", "AbortError"));
    });
  });
  return () => {
    globalThis.fetch = previousFetch;
  };
}

function fastTimers(ms = 5) {
  const previous = globalThis.setTimeout;
  globalThis.setTimeout = (fn, _delay, ...args) => previous(fn, ms, ...args);
  return () => {
    globalThis.setTimeout = previous;
  };
}

test("timeout budget mirrors the backend chain deadline plus five seconds", () => {
  // 一句 30 字：每站 13 秒 ×1.5 = 19.5，Edge 尾段 8.9，加 5 秒。
  assert.equal(ttsResponseTimeoutMs(30), 33400);
  // 1000 字：鏈封頂 150 秒，Edge 38 秒。
  assert.equal(ttsResponseTimeoutMs(1000), 193000);
});

test("a backend that never answers ends in onError instead of hanging", async () => {
  const restoreFetch = hangingFetch();
  const restoreTimers = fastTimers();
  const errors = [];
  let ended = false;
  try {
    const streamer = useTtsStreamer({
      onPcmChunk: () => {},
      onError: (err) => errors.push(err),
      onEnd: () => {
        ended = true;
      },
    });
    await streamer.speak("你好", { provider: "indextts" });
  } finally {
    restoreTimers();
    restoreFetch();
  }
  assert.equal(errors.length, 1);
  assert.ok(errors[0] instanceof TtsTimeoutError);
  assert.equal(ended, false);
});

test("a user cancel is still silent", async () => {
  const restoreFetch = hangingFetch();
  const errors = [];
  try {
    const streamer = useTtsStreamer({ onPcmChunk: () => {}, onError: (err) => errors.push(err) });
    const pending = streamer.speak("你好", { provider: "indextts" });
    streamer.cancel();
    await pending;
  } finally {
    restoreFetch();
  }
  assert.deepEqual(errors, []);
});
