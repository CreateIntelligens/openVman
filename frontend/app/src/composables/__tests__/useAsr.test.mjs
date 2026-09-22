import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { transformSync } from "esbuild";

const __dirname = dirname(fileURLToPath(import.meta.url));
const read = (p) => readFileSync(resolve(__dirname, "../..", p), "utf-8");
const appSource = read("App.vue");
const asrSource = read("composables/useAsr.ts");

test("App.vue exposes speaking signal for browser ASR to display listening indicator", () => {
  // app 端從此也有 speaking 訊號，「聆聽中」提示對瀏覽器引擎也會出現。
  assert.match(appSource, /const asrSpeaking = computed\(\(\) => \{[\s\S]*?useBrowserAsr\.value[\s\S]*?asr\.isSpeaking\.value/);
  assert.match(appSource, /:asr-speaking="asrSpeaking"/);
});

test("useAsr delegates to BrowserRecognizer from @shared/speech with isSpeaking", () => {
  assert.match(asrSource, /import \{[^}]*BrowserRecognizer[^}]*\} from '@shared\/speech'/);
  assert.match(asrSource, /isSpeaking:\s*readonly\(isSpeaking\)/);
  assert.match(asrSource, /continuous:\s*false/);
});

test("useAsr reactive refs update on speech start and end", async () => {
  let lastOptions = null;
  class MockBrowserRecognizer {
    constructor(options) {
      lastOptions = options;
      this.supported = true;
    }
    start() {
      lastOptions?.onListeningChange?.(true);
      return true;
    }
    stop() {
      lastOptions?.onListeningChange?.(false);
      lastOptions?.onSpeakingChange?.(false);
    }
    pause() { this.stop(); }
    resume() {}
    dispose() { this.stop(); }
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

  const transformed = transformSync(asrSource, {
    loader: "ts",
    format: "esm",
  }).code;

  const patched = transformed
    .replace(/import\s+{[^}]*}\s+from\s+['"]vue['"];?/, `
      const ref = globalThis.__mockVue.ref;
      const readonly = globalThis.__mockVue.readonly;
      const onUnmounted = globalThis.__mockVue.onUnmounted;
    `)
    .replace(/import\s+{[^}]*}\s+from\s+['"]@shared\/speech['"];?/, `
      const BrowserRecognizer = globalThis.__MockBrowserRecognizer;
    `);

  globalThis.__mockVue = mockVue;
  globalThis.__MockBrowserRecognizer = MockBrowserRecognizer;

  const dataUri = `data:text/javascript;base64,${Buffer.from(patched).toString("base64")}`;
  const { useAsr } = await import(dataUri);

  const asr = useAsr();
  assert.equal(asr.isListening.value, false);
  assert.equal(asr.isSpeaking.value, false);

  asr.start();
  assert.equal(asr.isListening.value, true);

  // 模擬收到說話訊號
  lastOptions.onSpeakingChange(true);
  assert.equal(asr.isSpeaking.value, true);

  lastOptions.onSpeakingChange(false);
  assert.equal(asr.isSpeaking.value, false);

  asr.stop();
  assert.equal(asr.isListening.value, false);
});
