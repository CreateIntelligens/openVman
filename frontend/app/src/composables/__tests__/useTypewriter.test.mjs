import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { build } from "esbuild";

const __dirname = dirname(fileURLToPath(import.meta.url));
const { outputFiles } = await build({
  entryPoints: [resolve(__dirname, "../useTypewriter.ts")],
  bundle: true, write: false, platform: "node", format: "esm", logLevel: "error",
});
const { useTypewriter } = await import(
  `data:text/javascript;base64,${Buffer.from(outputFiles[0].text).toString("base64")}`
);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

test("the typewriter reports done only after revealing every character", async () => {
  let shown = "";
  let done = 0;
  const tw = useTypewriter({ onBegin() {}, onChar: (c) => { shown += c; }, onDone: () => { done += 1; } });
  tw.start("abc");
  await sleep(60);
  assert.equal(done, 0);
  await sleep(150);
  assert.equal(shown, "abc");
  assert.equal(done, 1);
});

test("flush reveals the rest at once and reports done", () => {
  let shown = "";
  let done = 0;
  const tw = useTypewriter({ onBegin() {}, onChar: (c) => { shown += c; }, onDone: () => { done += 1; } });
  tw.start("hello");
  tw.flush();
  assert.equal(shown, "hello");
  assert.equal(done, 1);
});

test("TTS finishing its download does not dump the subtitle", () => {
  // 下載完就 flush，長回覆會在講到一半整段跳出（2026-09-29 使用者回報）。
  const app = readFileSync(resolve(__dirname, "../../App.vue"), "utf8");
  const onEnd = app.match(/onEnd:\s*\(\)\s*=>\s*\{([^}]*)\}/);
  assert.ok(onEnd, "ttsStreamer onEnd not found");
  assert.doesNotMatch(onEnd[1], /flush/);
});
