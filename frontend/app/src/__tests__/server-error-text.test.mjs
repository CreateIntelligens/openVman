import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import ts from "typescript";

const __dirname = dirname(fileURLToPath(import.meta.url));
const read = (path) => readFileSync(resolve(__dirname, path), "utf8");
const { outputText } = ts.transpileModule(read("../utils/serverErrorText.ts"), {
  compilerOptions: { module: ts.ModuleKind.ESNext },
});
const { serverErrorText, fatalErrorTitle } = await import(
  `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`
);

test("visitors never see raw error codes or HTTP statuses", () => {
  for (const [code, message] of [
    ["BRAIN_ERROR", "HTTP 500"],
    ["BRAIN_ERROR", "TypeError: Failed to fetch"],
    ["LLM_OVERLOAD", "upstream overloaded"],
    ["SOMETHING_NEW", "boom"],
  ]) {
    const text = serverErrorText(code, message);
    assert.doesNotMatch(text, /[A-Z_]{4,}|HTTP|\d{3}/, `${code} ${message} → ${text}`);
  }
});

test("the HTTP chat path is told apart by status and network failure", () => {
  assert.match(serverErrorText("BRAIN_ERROR", "HTTP 401"), /重新登入/);
  assert.match(serverErrorText("BRAIN_ERROR", "HTTP 429"), /稍等/);
  assert.match(serverErrorText("BRAIN_ERROR", "TypeError: Failed to fetch"), /網路/);
  assert.equal(serverErrorText("BRAIN_ERROR", "HTTP 500"), "暫時無法回答，請稍後再試。");
});

test("a retry delay is spoken in seconds", () => {
  assert.match(serverErrorText("LLM_OVERLOAD", "", 2400), /約 2 秒後可以再試/);
});

test("the toast and the fatal overlay use the friendly text", () => {
  const conversation = read("../composables/useAvatarConversation.ts");
  assert.doesNotMatch(conversation, /show\(`\$\{code\}: \$\{message\}/);
  assert.match(conversation, /serverErrorText\(code, message, retryAfterMs\)/);
  const overlay = read("../components/ErrorOverlay.vue");
  assert.match(overlay, /fatalErrorTitle\(code\)/);
  assert.equal(fatalErrorTitle("BRAIN_UNAVAILABLE"), "暫時無法使用");
});
