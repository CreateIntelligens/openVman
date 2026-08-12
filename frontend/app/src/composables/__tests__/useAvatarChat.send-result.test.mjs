import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../useAvatarChat.ts"), "utf8");

test("sendMessage reports whether the live message was accepted", () => {
  assert.match(source, /export interface SendMessageResult/);
  assert.match(source, /accepted:\s*boolean/);
  assert.match(source, /reason\?:\s*'empty'\s*\|\s*'not_ready'/);
  assert.match(source, /return \{ accepted: false, reason: 'not_ready' \}/);
  assert.match(source, /return \{ accepted: true \}/);
});

test("live readiness is checked before interrupting the active response", () => {
  const readinessCheck = source.indexOf("currentMode === 'live'");
  const stopResponse = source.indexOf("stopActiveResponse()", readinessCheck);

  assert.notEqual(readinessCheck, -1);
  assert.notEqual(stopResponse, -1);
  assert.ok(readinessCheck < stopResponse);
});

test("connect resolves only after server_init_ack", () => {
  const onOpen = source.indexOf("socket.onopen");
  const onMessage = source.indexOf("socket.onmessage", onOpen);
  const initAck = source.indexOf("case 'server_init_ack'");

  assert.notEqual(onOpen, -1);
  assert.notEqual(onMessage, -1);
  assert.notEqual(initAck, -1);
  assert.doesNotMatch(
    source.slice(onOpen, onMessage),
    /resolvePendingConnect\(\)/,
  );
  assert.match(source.slice(initAck), /resolvePendingConnect\(\)/);
});

test("automatic reconnect regenerates derived client URLs", () => {
  assert.match(source, /lastUrlOverride = url/);
  assert.match(source, /void connect\(url\)\.catch\(console\.error\)/);
  assert.doesNotMatch(source, /void connect\(wsUrl\)\.catch\(console\.error\)/);
});

test("text and live responses retain RAG images and links for the assistant bubble", () => {
  assert.match(source, /case 'server_search_results'/);
  assert.match(source, /applyResponseMedia\(\{ citations: data\.citations \}\)/);
  assert.match(source, /applyResponseMedia\(data\)/);
  assert.match(source, /source\.imageId = activeImageId/);
  assert.match(source, /source\.projectId = currentProjectId/);
  assert.match(source, /source\.url = activeUrl/);
});
