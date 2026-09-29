import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

// 2026-09-30：虛擬人講完後麥克風不會恢復，每輪要重按；串流辨識的暫定字幕也不刷新閒置計時。
const __dirname = dirname(fileURLToPath(import.meta.url));
const app = readFileSync(resolve(__dirname, "../App.vue"), "utf8");

test("streaming interims keep the microphone from idling out mid-sentence", () => {
  const block = app.match(/const streamAsr = useStreamAsr\(\{([\s\S]*?)onResult:/);
  assert.ok(block);
  assert.match(block[1], /onInterim:[\s\S]*markAsrActivity\(\)/);
});

test("listening resumes after the reply with a shorter idle window", () => {
  assert.match(app, /const ASR_RESUME_IDLE_TIMEOUT_MS = 6_000;/);
  const resume = app.match(/watch\(avatarResponding, \(responding\) => \{([\s\S]*?)\n\}\);/);
  assert.ok(resume, "resume watcher missing");
  assert.match(resume[1], /if \(responding \|\| !resumeAsrAfterReply\) return;/);
  assert.match(resume[1], /active\.resume\(\)/);
  assert.match(resume[1], /void active\.start\(\)/);
  assert.match(resume[1], /scheduleAsrIdleTimer\(ASR_RESUME_IDLE_TIMEOUT_MS\)/);
});

test("the stream is closed rather than left idle while the avatar answers", () => {
  // 閒置的串流被 Gemini 斷掉會被當成不可用，之後一直退回批次辨識。
  assert.match(app, /if \(activeAsr\.value === streamAsr\) activeAsr\.value\.stop\(\);\s*else activeAsr\.value\.pause\(\);/);
});

test("the gap while TTS synthesises still counts as answering", () => {
  const block = app.match(/const avatarResponding = computed\(\(\) =>([\s\S]*?)\);/);
  assert.match(block[1], /ttsPending\.value/);
  assert.match(app, /ttsPending\.value = true;\s*turnTiming\.mark\("tts_start"\);\s*void ttsStreamer\.speak/);
});

test("turning the microphone off by hand is not undone after the reply", () => {
  const toggle = app.match(/function handleAsrToggle\(\): void \{([\s\S]*?)\n\}/);
  assert.match(toggle[1], /resumeAsrAfterReply = false;\s*active\.stop\(\);/);
});
