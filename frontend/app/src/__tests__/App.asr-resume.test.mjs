import { readAppComposition, readAppModule } from "./helpers/appSources.mjs";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { computed, effectScope, nextTick, ref, watch } from "vue";

// 2026-09-30：虛擬人講完後麥克風不會恢復，每輪要重按；串流辨識的暫定字幕也不刷新閒置計時。
const __dirname = dirname(fileURLToPath(import.meta.url));
const app = readAppComposition("useAvatarVoiceInput", "useAvatarConversation");

test("streaming interims keep the microphone from idling out mid-sentence", () => {
  const block = app.match(/const streamAsr = useStreamAsr\(\{([\s\S]*?)onResult:/);
  assert.ok(block);
  assert.match(block[1], /onInterim:[\s\S]*markAsrActivity\(\)/);
});

test("listening resumes after the reply with a shorter idle window", () => {
  assert.match(app, /const ASR_RESUME_IDLE_TIMEOUT_MS = 6_000;/);
  const resume = app.match(/watch\(avatarResponding, \(responding\) => \{([\s\S]*?)\n\s*\}\);/);
  assert.ok(resume, "resume watcher missing");
  assert.match(resume[1], /if \(responding\) return;/);
  assert.match(resume[1], /if \(!resumeAsrAfterReply\) \{/);
  assert.match(resume[1], /active\.resume\(\)/);
  assert.match(resume[1], /void active\.start\(\)/);
  assert.match(resume[1], /scheduleAsrIdleTimer\(ASR_RESUME_IDLE_TIMEOUT_MS\)/);
});

test("the stream is closed rather than left idle while the avatar speaks", () => {
  // 閒置的串流被 Gemini 斷掉會被當成不可用，之後一直退回批次辨識。
  assert.match(app, /if \(activeAsr\.value === streamAsr && INTERRUPT_WHILE_SPEAKING\) return;/);
  assert.match(app, /if \(activeAsr\.value === streamAsr\) activeAsr\.value\.stop\(\);\s*else activeAsr\.value\.pause\(\);/);
});

test("the gap while TTS synthesises still counts as answering", () => {
  const block = app.match(/const avatarSpeaking = computed\(\(\) =>([\s\S]*?)\);/);
  assert.match(block[1], /ttsPending\.value/);
  assert.match(app, /ttsPending\.value = true;\s*turnTiming\.mark\("tts_start"\);\s*void ttsStreamer\.speak/);
});

test("turning the microphone off by hand is not undone after the reply", () => {
  const toggle = app.match(/function handleAsrToggle\(\): void \{([\s\S]*?)\n\s*\}/);
  assert.match(toggle[1], /resumeAsrAfterReply = false;\s*active\.stop\(\);/);
});

for (const streaming of [true, false]) {
  test(`actual Vue watchers keep listening while thinking and pause ${streaming ? 'stream' : 'batch'} only while speaking`, async () => {
    const calls = [];
    const active = {
      isListening: ref(true),
      isStarting: ref(false),
      stop() { calls.push('stop'); this.isListening.value = false; },
      pause() { calls.push('pause'); },
      resume() { calls.push('resume'); },
      start() { calls.push('start'); this.isListening.value = true; },
    };
    const chat = { state: ref('IDLE') };
    const ttsPending = ref(false);
    const avatarSpeaking = computed(() => chat.state.value === 'SPEAKING' || ttsPending.value);
    const avatarResponding = computed(() => chat.state.value === 'THINKING' || avatarSpeaking.value);
    // Execute the production watcher bodies with Vue's real scheduler.
    const voice = readAppModule('useAvatarVoiceInput');
    const start = voice.indexOf('watch(() => chat.state.value, (newState) => {');
    const end = voice.indexOf('onUnmounted(() => {', start);
    assert.ok(start >= 0 && end > start);
    const install = new Function(
      'watch', 'chat', 'activeAsr', 'streamAsr', 'avatarSpeaking', 'avatarResponding',
      'asrStarting',
      'triggerStageAvatarGesture', 'clearAsrIdleTimer', 'scheduleAsrIdleTimer',
      `let resumeAsrAfterReply = false; const ASR_RESUME_IDLE_TIMEOUT_MS = 6000; const INTERRUPT_WHILE_SPEAKING = false;\n${voice.slice(start, end)}`,
    );
    const scope = effectScope();
    try {
      scope.run(() => install(watch, chat, { value: active }, streaming ? active : {},
        avatarSpeaking, avatarResponding, ref(false), () => {}, () => calls.push('clear'), ms => calls.push(ms)));
      // 在想：不出聲，麥克風照開（可以補一句），只是不倒數。
      chat.state.value = 'THINKING'; await nextTick();
      assert.deepEqual(calls, ['clear']);
      // 回答到了、開始合成聲音：這時才關。
      ttsPending.value = true; chat.state.value = 'IDLE'; await nextTick();
      assert.deepEqual(calls.slice(1), ['clear', streaming ? 'stop' : 'pause']);
      ttsPending.value = false; await nextTick();
      assert.deepEqual(calls.slice(3), [streaming ? 'start' : 'resume', 6000]);
      await nextTick();
      assert.equal(calls.length, 5);
    } finally {
      scope.stop();
    }
  });
}

test("a reply that never speaks starts the idle countdown on the open microphone", async () => {
  const calls = [];
  const active = { isListening: ref(true), stop() {}, pause() {}, resume() {}, start() {} };
  const chat = { state: ref('IDLE') };
  const avatarSpeaking = computed(() => false);
  const avatarResponding = computed(() => chat.state.value === 'THINKING');
  const voice = readAppModule('useAvatarVoiceInput');
  const start = voice.indexOf('watch(() => chat.state.value, (newState) => {');
  const end = voice.indexOf('onUnmounted(() => {', start);
  const install = new Function(
    'watch', 'chat', 'activeAsr', 'streamAsr', 'avatarSpeaking', 'avatarResponding',
    'asrStarting',
    'triggerStageAvatarGesture', 'clearAsrIdleTimer', 'scheduleAsrIdleTimer',
    `let resumeAsrAfterReply = false; const ASR_RESUME_IDLE_TIMEOUT_MS = 6000; const INTERRUPT_WHILE_SPEAKING = false;\n${voice.slice(start, end)}`,
  );
  const scope = effectScope();
  try {
    scope.run(() => install(watch, chat, { value: active }, {}, avatarSpeaking, avatarResponding, ref(false),
      () => {}, () => calls.push('clear'), ms => calls.push(ms)));
    chat.state.value = 'THINKING'; await nextTick();
    // 出錯：沒出聲就結束，麥克風還開著，不能一直開下去。
    chat.state.value = 'ERROR'; await nextTick();
    assert.deepEqual(calls, ['clear', 6000]);
  } finally {
    scope.stop();
  }
});
