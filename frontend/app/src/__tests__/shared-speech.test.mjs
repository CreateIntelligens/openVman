import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { buildSync } from "esbuild";

const __dirname = dirname(fileURLToPath(import.meta.url));

function loadSharedTs(relativePath) {
  const fullPath = resolve(__dirname, "../../../shared/speech", relativePath);
  const result = buildSync({
    entryPoints: [fullPath],
    bundle: true,
    format: "esm",
    write: false,
    platform: "browser",
    external: ["@ricky0123/vad-web"],
  });
  const code = result.outputFiles[0].text;
  return `data:text/javascript;base64,${Buffer.from(code).toString("base64")}`;
}

test("shared-speech: VAD dependency version synchronization (D4)", () => {
  const adminPkg = JSON.parse(
    readFileSync(resolve(__dirname, "../../../admin/package.json"), "utf8"),
  );
  const appPkg = JSON.parse(
    readFileSync(resolve(__dirname, "../../package.json"), "utf8"),
  );

  const adminVad = (adminPkg.dependencies?.["@ricky0123/vad-web"] || "").replace(/^[^\d]*/, "");
  const appVad = (appPkg.dependencies?.["@ricky0123/vad-web"] || "").replace(/^[^\d]*/, "");

  assert.ok(appVad, "app vad version must exist");
  assert.equal(appVad, adminVad, "both packages must use exact same vad version");
  assert.equal(appVad, "0.0.30");
});

test("shared-speech: TTS voice pairing validation (D9)", async () => {
  const modUrl = loadSharedTs("tts/selection.ts");
  const { resolveTtsVoiceSelection, pickProviderVoice } = await import(modUrl);

  const providers = [
    {
      id: "gemini-tts",
      name: "Gemini TTS",
      default_voice: "Kore",
      voices: ["Puck", "Charon", "Kore"],
    },
    {
      id: "indextts",
      name: "IndexTTS",
      default_voice: "voice-a",
      voices: ["voice-a", "voice-b"],
    },
  ];

  // 1. 合法存檔保留
  const valid = resolveTtsVoiceSelection({
    availableProviders: providers,
    savedProvider: "gemini-tts",
    savedVoice: "Charon",
    accountDefaultProvider: "gemini-tts",
    accountDefaultVoice: "Puck",
  });
  assert.equal(valid.provider, "gemini-tts");
  assert.equal(valid.voice, "Charon");
  assert.equal(valid.changed, false);

  // 2. 聲音失效整組退回帳號預設
  const invalidVoice = resolveTtsVoiceSelection({
    availableProviders: providers,
    savedProvider: "gemini-tts",
    savedVoice: "non-existent-voice",
    accountDefaultProvider: "gemini-tts",
    accountDefaultVoice: "Puck",
  });
  assert.equal(invalidVoice.provider, "gemini-tts");
  assert.equal(invalidVoice.voice, "Puck");
  assert.equal(invalidVoice.changed, true);

  // 3. 引擎失效整組退回帳號預設，絕不拼出存檔引擎+預設聲音
  const invalidProvider = resolveTtsVoiceSelection({
    availableProviders: providers,
    savedProvider: "unknown-engine",
    savedVoice: "Puck",
    accountDefaultProvider: "gemini-tts",
    accountDefaultVoice: "Kore",
  });
  assert.equal(invalidProvider.provider, "gemini-tts");
  assert.equal(invalidProvider.voice, "Kore");
  assert.equal(invalidProvider.changed, true);

  // 4. pickProviderVoice 優先採用合法 default_voice
  assert.equal(pickProviderVoice(providers[0]), "Kore");
});

test("shared-speech: TTS fallback parser and Chinese notice (D10)", async () => {
  const modUrl = loadSharedTs("tts/fallback.ts");
  const { parseTtsFallback, formatTtsFallbackMessage } = await import(modUrl);

  const headers = new Headers({
    "X-TTS-Fallback": "true",
    "X-TTS-Provider": "edge",
    "X-TTS-Fallback-Reason": "GPU node unreachable",
  });

  const parsed = parseTtsFallback(headers);
  assert.ok(parsed);
  assert.equal(parsed.provider, "edge");
  assert.equal(parsed.reason, "GPU node unreachable");

  const notice = formatTtsFallbackMessage(parsed.provider, parsed.reason);
  assert.equal(notice, "語音引擎已自動切換為 edge（原因：GPU node unreachable）");
});

test("shared-speech: Storage scope and key migration (D11)", async () => {
  const modUrl = loadSharedTs("storage.ts");
  const {
    setStorageScope,
    currentStorageScope,
    readScoped,
    writeScoped,
    removeScoped,
    hasScoped,
    SPEECH_STORAGE_KEYS,
  } = await import(modUrl);

  const mockStorage = new Map();
  globalThis.window = {
    localStorage: {
      getItem(k) { return mockStorage.has(k) ? mockStorage.get(k) : null; },
      setItem(k, v) { mockStorage.set(k, String(v)); },
      removeItem(k) { mockStorage.delete(k); },
    },
  };

  setStorageScope("user_a");
  assert.equal(currentStorageScope(), "user_a");

  writeScoped("tts_engine", "gemini-tts");
  assert.equal(readScoped("tts_engine"), "gemini-tts");

  // 舊鍵遷移測試
  mockStorage.set("avatar.tts_engine", "indextts");
  const migrated = readScoped(SPEECH_STORAGE_KEYS.TTS_PROVIDER, null);
  assert.equal(migrated, "indextts");
  // 遷移後寫入新鍵
  assert.equal(mockStorage.get(`speech.tts_provider::user_a`), "indextts");
});

test("shared-speech: WAV header detection and 7-byte safety", async () => {
  const modUrl = loadSharedTs("tts/pcm-stream.ts");
  const { looksLikeWav, wavSampleRate, wavDataOffset, concatBytes } = await import(modUrl);

  // 構造 24000 Hz WAV 標頭 (44 bytes)
  const header = new Uint8Array(44);
  header.set([...Buffer.from("RIFF")], 0);
  header.set([...Buffer.from("WAVE")], 8);
  header.set([...Buffer.from("fmt ")], 12);
  const view = new DataView(header.buffer);
  view.setUint32(16, 16, true); // fmt chunk size
  view.setUint16(20, 1, true);  // PCM format
  view.setUint16(22, 1, true);  // Mono
  view.setUint32(24, 24000, true); // 24000 Hz
  view.setUint32(28, 48000, true); // Byte rate
  view.setUint16(32, 2, true);  // Block align
  view.setUint16(34, 16, true); // Bits per sample
  header.set([...Buffer.from("data")], 36);
  view.setUint32(40, 1000, true);

  // 模擬第一個網路 chunk 只有 7 bytes
  const chunk1 = header.subarray(0, 7);
  const chunk2 = header.subarray(7);

  // 未累積完整前不能判斷完整
  assert.equal(looksLikeWav(chunk1), false);

  // 累積滿後正確偵測
  const combined = concatBytes(chunk1, chunk2);
  assert.equal(looksLikeWav(combined), true);
  assert.equal(wavSampleRate(combined), 24000);
  assert.equal(wavDataOffset(combined), 44);
});

test("shared-speech: SpeechController state machine (D1, D2, D3)", async () => {
  const modUrl = loadSharedTs("asr/controller.ts");
  const { SpeechController } = await import(modUrl);

  class MockUnit {
    constructor() {
      this.listening = false;
      this.speaking = false;
      this.supported = true;
    }
    start() {
      this.listening = true;
      return true;
    }
    stop() {
      this.listening = false;
      this.speaking = false;
    }
  }

  const browser = new MockUnit();
  const vad = new MockUnit();
  const recorder = new MockUnit();
  const http = {
    request: () => Promise.resolve(new Response(JSON.stringify({ value: "", effective: "breeze", allowed: ["breeze"] }))),
    parseError: () => "error",
  };

  const controller = new SpeechController({
    http,
    browserRecognizer: browser,
    vadRecognizer: vad,
    serverRecorder: recorder,
  });

  // D1: 未設定或預設時一律為伺服器引擎
  assert.equal(controller.engine, "server");
  assert.equal(controller.inputMode, "continuous");
  assert.equal(controller.activeUnit, vad);

  // 初始收音
  await controller.startListening();
  assert.equal(controller.listening, true);

  // D2: 模擬處於 browser 引擎時發生終止錯誤
  const browserController = new SpeechController({
    http,
    browserRecognizer: browser,
    vadRecognizer: vad,
    serverRecorder: recorder,
    initialProvider: { value: "browser", effective: "browser", allowed: ["browser"] },
  });
  assert.equal(browserController.engine, "browser");
  await browserController.startListening();
  assert.equal(browserController.listening, true);

  // 瀏覽器端拋出 not-allowed 終止性錯誤 -> 自動降級到伺服器引擎 (vad) 且記憶體內切換並繼續保持收音
  browserController.handleRecognizerError("not-allowed");
  assert.equal(browserController.engine, "server");
  assert.equal(browserController.activeUnit, vad);
  assert.equal(browserController.listening, true);

  browserController.dispose();
  controller.dispose();
});
