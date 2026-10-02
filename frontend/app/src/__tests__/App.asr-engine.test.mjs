import { readAppComposition, readAppModule } from "./helpers/appSources.mjs";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import ts from "typescript";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readAppComposition("useAvatarVoiceInput", "useAsrPreferences", "useAvatarConversation", "useAvatarCamera");
const engineSource = readFileSync(
  resolve(__dirname, "../../../shared/speech/asr/engines.ts"), "utf8",
);
const { outputText } = ts.transpileModule(engineSource, {
  compilerOptions: { module: ts.ModuleKind.ESNext },
});
const { isStreamAsrEngine, ASR_ENGINE_NOTES } = await import(
  `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`
);

// 執行 App 的實際選擇條件，才能抓到移除台語或可用性閘門的回歸。
const streamPredicate = source.match(
  /const useStreamAsrEngine = computed\(\s*\(\) => ([\s\S]*?),\s*\);/,
);
assert.ok(streamPredicate, "App exposes its streaming selection predicate");
const selectStream = new Function(
  "isStreamAsrEngine", "myAsrProvider", "streamAvailable", "languageRoutes",
  `return ${streamPredicate[1]};`,
);

function usesStream(provider, available = true, taiwaneseOn = false) {
  return selectStream(
    isStreamAsrEngine, { value: provider }, { value: available },
    { taiwaneseOn: { value: taiwaneseOn } },
  );
}

test("Gemini Live and R2T2 Live select streaming while batch engines do not", () => {
  assert.equal(usesStream("gemini-live"), true);
  assert.equal(usesStream("r2t2-live"), true);
  assert.equal(usesStream("r2t2-dev-live"), true);
  for (const provider of ["r2t2", "r2t2-dev", "breeze", "browser", ""]) {
    assert.equal(usesStream(provider), false);
  }
  assert.match(source, /if \(useStreamAsrEngine\.value\) return streamAsr;/);
  assert.match(ASR_ENGINE_NOTES["r2t2-live"].label, /串流/);
  assert.match(ASR_ENGINE_NOTES["r2t2-dev-live"].label, /dev 串流/);
});

test("both streaming engines fall back when Taiwanese routing is enabled", () => {
  for (const provider of ["gemini-live", "r2t2-live", "r2t2-dev-live"]) {
    assert.equal(usesStream(provider, true, true), false);
  }
});

test("both streaming engines fall back after streaming becomes unavailable", () => {
  for (const provider of ["gemini-live", "r2t2-live", "r2t2-dev-live"]) {
    assert.equal(usesStream(provider, false), false);
  }
});

test("the chat picks an engine instead of always using the browser one", () => {
  assert.match(source, /useServerAsr/);
  assert.match(source, /const useBrowserAsr = computed/);
  // 切換要看使用者選的引擎，不是寫死用 asr。伺服器引擎再分兩種：VAD 可用就
  // 講完自動送，否則退回按鍵錄音。
  assert.match(source, /if \(useBrowserAsr\.value\) return asr;/);
  assert.match(source, /return vadAvailable\.value \? vadAsr : serverAsr;/);
});

test("browser recognition needs both the capability check and the account choice", () => {
  // 只看 isSupported 會漏掉「使用者沒選瀏覽器辨識」的情況，反過來只看選擇
  // 則會在不支援的瀏覽器上整個壞掉。
  assert.match(source, /myAsrProvider\.value === BROWSER_ASR && asr\.isSupported\.value/);
});

test("a terminal browser error falls back to the server engine", () => {
  // isSupported 是 true 但使用者拒絕麥克風時，瀏覽器辨識照樣不能用，那要
  // 當場換引擎而不是叫使用者改用鍵盤。
  assert.match(source, /BROWSER_FALLBACK_ERRORS/);
  for (const code of ["not-allowed", "audio-capture", "service-not-allowed"]) {
    assert.match(source, new RegExp(`"${code}"`));
  }
});

test("a one-off failure does not switch the engine away", () => {
  // no-speech 是這一次沒講話，重試即可；把它算進 fallback 會讓使用者無故
  // 被換掉引擎。
  const block = source.slice(
    source.indexOf("BROWSER_FALLBACK_ERRORS = new Set"),
    source.indexOf("]);", source.indexOf("BROWSER_FALLBACK_ERRORS = new Set")),
  );
  assert.doesNotMatch(block, /no-speech/);
  assert.doesNotMatch(block, /start-failed/);
});

test("the account's engine is read from the backend, not assumed", () => {
  assert.match(source, /fetchMyAsrProvider/);
  // 讀不到偏好不該讓使用者不能講話。
  assert.match(source, /fetchMyAsrProvider\(\)[\s\S]{0,400}\.catch\(/);
});

test("the settings modal gets the engines this account may pick", () => {
  // 之前只做了切換邏輯卻沒有選單，使用者在聊天室根本看不到這個功能。
  assert.match(source, /:asr-engines="asrEngines"/);
  // 沒選過（或選的被收回授權）時顯示實際在用的引擎，不再有「預設」選項。
  assert.match(source, /:asr-provider="asrProviderShown"/);
  assert.match(source, /myAsrEffective\.value = profile\.effective/);
  assert.match(source, /@asr-provider-change="handleAsrProviderChange"/);
});

test("a failed save rolls the selection back", () => {
  // 存不起來卻留著新選擇，畫面會顯示一個其實沒生效的引擎。
  assert.match(source, /setMyAsrProvider\(provider\)[\s\S]{0,200}\.catch/);
  assert.match(source, /myAsrProvider\.value = previous/);
});

test("the camera button is hidden, not just disabled, when vision is off", () => {
  // 一個永遠按不下去的按鈕只是雜訊。
  const bar = readFileSync(
    resolve(__dirname, "../components/controls/ControlBar.vue"), "utf8",
  );
  assert.match(bar, /v-if="cameraAvailable"/);
  assert.doesNotMatch(bar, /cameraDisabled/);
});

test("vision availability starts unknown so the button does not flicker", () => {
  // 預設 true 會先亮一下才消失；預設 false 則是真的可用時先消失再出現。
  assert.match(source, /visionAvailable = ref<boolean \| null>\(null\)/);
  assert.match(source, /visionAvailable === true/);
});

test("every voice turn is timed from speech to playback", () => {
  // 要從 log 撈整個流程多久（backend/logs/turn_timing.jsonl），缺一個點那段就量不到。
  assert.equal((source.match(/turnTiming\.asrDone\(\);/g) ?? []).length, 4, "四種 ASR 都要記辨識完成");
  assert.match(source, /if \(speaking\) \{\s*turnTiming\.speechStarted\(\);[\s\S]*?\} else \{\s*turnTiming\.speechEnded\(\);/);
  // 思考中補一句：前一輪記成 merged，不算失敗。
  assert.match(source, /turnTiming\.begin\(chat\.mergesWithPending\(sourcePath\) \? "merged" : "superseded"\);/);
  assert.match(source, /turnTiming\.mark\("sent"\);\s*const result: SendMessageResult = chat\.sendMessage\(/);
  assert.match(source, /turnTiming\.mark\("reply_done"\);/);
  assert.match(source, /turnTiming\.mark\("tts_start"\);\s*void ttsStreamer\.speak\(/);
  assert.match(source, /onFirstAudio: \(\) => \{\s*turnTiming\.mark\("first_audio"\);/);
  assert.match(source, /onPlaybackStart: \(\) => \{[\s\S]{0,120}turnTiming\.playbackStarted\(\);/);
  assert.match(source, /onStopAudio: \(\) => \{\s*turnTiming\.interrupted\(\);/);
});
