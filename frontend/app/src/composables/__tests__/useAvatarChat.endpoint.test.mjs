import { avatarChatSource } from "./helpers/avatarChatModule.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const source = avatarChatSource;

test("text-mode chat defaults to the backend Brain facade endpoint", () => {
  assert.match(
    source,
    /export const DEFAULT_TEXT_CHAT_ENDPOINT = ['"]\/api\/v1\/chat['"]/,
  );
  assert.match(
    source,
    /const chatEndpoint = options\.chatEndpoint \?\? DEFAULT_TEXT_CHAT_ENDPOINT/,
  );
  assert.match(
    source,
    /export const DEFAULT_TEXT_CHAT_STREAM_ENDPOINT = ['"]\/api\/v1\/chat\/stream['"]/,
  );
  assert.doesNotMatch(source, /['"]\/api\/v1\/brain\/chat['"]/);
});
