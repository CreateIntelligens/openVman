import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { transformSync } from "esbuild";

const __dirname = dirname(fileURLToPath(import.meta.url));
const read = (p) => readFileSync(resolve(__dirname, "../..", p), "utf-8");
const appSource = read("App.vue");
const serverAsrSource = read("composables/useServerAsr.ts");

test("App.vue uses unified getAsrErrorMessage from @shared/speech", () => {
  assert.match(appSource, /import \{[^}]*getAsrErrorMessage[^}]*\} from "@shared\/speech"/);
  assert.match(appSource, /asrError\.value = getAsrErrorMessage\(error/);
});

test("useServerAsr delegates to ServerRecorder from @shared/speech", () => {
  assert.match(serverAsrSource, /import \{[^}]*ServerRecorder[^}]*\} from '@shared\/speech'/);
  assert.match(serverAsrSource, /new ServerRecorder\(\{/);
  assert.match(serverAsrSource, /onUnmounted\(\(\) => \{\s*recorder\.dispose\(\)/);
});

test("useServerAsr reactive refs update on recording and transcribing changes", async () => {
  // 建立可測試的 useServerAsr 執行環境
  let lastOptions = null;
  class MockServerRecorder {
    constructor(options) {
      lastOptions = options;
      this.supported = true;
    }
    start() {
      lastOptions?.onRecordingChange?.(true);
      return Promise.resolve(true);
    }
    stop() {
      lastOptions?.onRecordingChange?.(false);
    }
    pause() { this.stop(); }
    resume() {}
    dispose() {
      lastOptions?.onRecordingChange?.(false);
      lastOptions?.onTranscribingChange?.(false);
    }
  }

  const mockVue = {
    ref: (init) => {
      let val = init;
      return {
        get value() { return val; },
        set value(v) { val = v; },
      };
    },
    readonly: (r) => r,
    onUnmounted: (fn) => { fn._unmount = true; },
  };

  const transformed = transformSync(serverAsrSource, {
    loader: "ts",
    format: "esm",
  }).code;

  // 替換模組匯入為本機 mock
  const patched = transformed
    .replace(/import\s+{[^}]*}\s+from\s+['"]vue['"];?/, `
      const ref = globalThis.__mockVue.ref;
      const readonly = globalThis.__mockVue.readonly;
      const onUnmounted = globalThis.__mockVue.onUnmounted;
    `)
    .replace(/import\s+{[^}]*}\s+from\s+['"]@shared\/speech['"];?/, `
      const ServerRecorder = globalThis.__MockServerRecorder;
    `)
    .replace(/import\s+{[^}]*}\s+from\s+['"]\.\.\/api\/http['"];?/, `
      const apiFetch = () => Promise.resolve(new Response("{}"));
      const parseJson = () => Promise.resolve({});
    `);

  globalThis.__mockVue = mockVue;
  globalThis.__MockServerRecorder = MockServerRecorder;

  const dataUri = `data:text/javascript;base64,${Buffer.from(patched).toString("base64")}`;
  const { useServerAsr } = await import(dataUri);

  const onResult = (text) => { receivedResult = text; };
  const onError = (code) => { receivedError = code; };
  let receivedResult = null;
  let receivedError = null;

  const asr = useServerAsr({ onResult, onError });

  assert.equal(asr.isListening.value, false);
  assert.equal(asr.isTranscribing.value, false);
  assert.equal(asr.isSupported.value, true);

  // 啟動錄音 -> isListening 應變為 true
  await asr.start();
  assert.equal(asr.isListening.value, true);

  // 停止錄音 -> isListening 應變為 false
  asr.stop();
  assert.equal(asr.isListening.value, false);

  // 轉錄中狀態觸發
  lastOptions.onTranscribingChange(true);
  assert.equal(asr.isTranscribing.value, true);
  lastOptions.onTranscribingChange(false);
  assert.equal(asr.isTranscribing.value, false);

  // 結果與錯誤回呼傳遞
  lastOptions.onResult("測試辨識文字");
  assert.equal(receivedResult, "測試辨識文字");

  lastOptions.onError("not-allowed");
  assert.equal(receivedError, "not-allowed");
});
