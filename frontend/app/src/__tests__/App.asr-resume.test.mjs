import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { computed, effectScope, nextTick, ref, watch } from "vue";

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

for (const streaming of [true, false]) {
  test(`actual Vue watchers wait for TTS and resume ${streaming ? 'stream' : 'batch'} once`, async () => {
    const calls = [];
    const active = {
      isListening: ref(true),
      stop() { calls.push('stop'); this.isListening.value = false; },
      pause() { calls.push('pause'); },
      resume() { calls.push('resume'); },
      start() { calls.push('start'); this.isListening.value = true; },
    };
    const chat = { state: ref('IDLE') };
    const ttsPending = ref(false);
    const avatarResponding = computed(() => chat.state.value !== 'IDLE' || ttsPending.value);
    // Execute the production watcher bodies with Vue's real scheduler.
    const start = app.indexOf('watch(() => chat.state.value, (newState) => {');
    const end = app.indexOf('watch(showSettings,', start);
    assert.ok(start >= 0 && end > start);
    const install = new Function(
      'watch', 'chat', 'activeAsr', 'streamAsr', 'avatarResponding',
      'triggerStageAvatarGesture', 'clearAsrIdleTimer', 'scheduleAsrIdleTimer',
      `let resumeAsrAfterReply = false; const ASR_RESUME_IDLE_TIMEOUT_MS = 6000;\n${app.slice(start, end)}`,
    );
    const scope = effectScope();
    try {
      scope.run(() => install(watch, chat, { value: active }, streaming ? active : {},
        avatarResponding, () => {}, () => calls.push('clear'), ms => calls.push(ms)));
      chat.state.value = 'THINKING'; await nextTick();
      assert.deepEqual(calls, ['clear', streaming ? 'stop' : 'pause']);
      ttsPending.value = true; chat.state.value = 'IDLE'; await nextTick();
      assert.equal(calls.length, 2);
      ttsPending.value = false; await nextTick();
      assert.deepEqual(calls.slice(2), [streaming ? 'start' : 'resume', 6000]);
      await nextTick();
      assert.equal(calls.length, 4);
    } finally {
      scope.stop();
    }
  });
}
