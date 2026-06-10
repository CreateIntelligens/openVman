import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../useAvatarChat.ts"), "utf8");

test("text-mode chat defaults to the backend Brain facade endpoint", () => {
  assert.match(
    source,
    /export const DEFAULT_TEXT_CHAT_ENDPOINT = ['"]\/api\/chat['"]/,
  );
  assert.match(
    source,
    /fetch\(options\.chatEndpoint \?\? DEFAULT_TEXT_CHAT_ENDPOINT,/,
  );
  assert.doesNotMatch(source, /['"]\/api\/brain\/chat['"]/);
});
