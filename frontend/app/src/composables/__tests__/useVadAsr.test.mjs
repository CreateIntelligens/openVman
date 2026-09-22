import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { transformSync } from "esbuild";

const __dirname = dirname(fileURLToPath(import.meta.url));
const read = (p) => readFileSync(resolve(__dirname, "../..", p), "utf-8");
const source = read("composables/useVadAsr.ts");
const app = read("App.vue");
const vadRecognizerSource = readFileSync(
  resolve(__dirname, "../../../../shared/speech/asr/vad-recognizer.ts"),
  "utf-8",
);

async function loadWav() {
  const wavPath = resolve(__dirname, "../../../../shared/speech/audio/wav.ts");
  const { code } = transformSync(readFileSync(wavPath, "utf-8"), { loader: "ts", format: "esm" });
  return import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);
}

test("encodeWav writes a header the backend's decoder will accept", async () => {
  const { encodeWav } = await loadWav();
  const blob = encodeWav(new Float32Array([0, 1, -1, 2]), 16000);
  const view = new DataView(await blob.arrayBuffer());
  const tag = (o) => String.fromCharCode(...[0, 1, 2, 3].map((i) => view.getUint8(o + i)));

  assert.equal(blob.type, "audio/wav");
  assert.equal(tag(0), "RIFF");
  assert.equal(tag(8), "WAVE");
  assert.equal(tag(36), "data");
  assert.equal(view.getUint16(22, true), 1, "mono");
  assert.equal(view.getUint32(24, true), 16000, "sample rate");
  assert.equal(view.getUint16(34, true), 16, "bits per sample");
  assert.equal(view.getUint32(40, true), 8, "4 個取樣 × 2 bytes");
  assert.equal(view.byteLength, 44 + 8);
  // 取樣值：0、滿刻度正、滿刻度負；超出 ±1 的要夾住而不是溢位繞回去。
  assert.equal(view.getInt16(44, true), 0);
  assert.equal(view.getInt16(46, true), 0x7fff);
  assert.equal(view.getInt16(48, true), -0x8000);
  assert.equal(view.getInt16(50, true), 0x7fff);
});

test("one press captures one sentence, then the microphone closes", () => {
  // App 端使用 per-utterance 模式，講完先關麥克風再送出，防止喇叭聲音回授。
  assert.match(source, /commitMode:\s*['"]per-utterance['"]/);
  const onSpeechEnd = vadRecognizerSource.slice(
    vadRecognizerSource.indexOf("this.callbacks.onSpeechEnd = "),
    vadRecognizerSource.indexOf("this.callbacks.onVADMisfire = "),
  );
  assert.ok(onSpeechEnd.indexOf("this.stop()") < onSpeechEnd.indexOf("this.send(audio)"));
});

test("the model is shared with the admin console instead of duplicated", () => {
  assert.match(vadRecognizerSource, /VAD_ASSET_BASE = '\/admin\/vad\/'/);
});

test("a VAD that cannot load falls back to push-to-talk and starts recording", () => {
  // 模型或 WASM 載不到（內網連不到 CDN）時，使用者按了麥克風不能什麼都沒發生。
  assert.match(vadRecognizerSource, /this\.emitError\('vad-unavailable'\)/);
  assert.match(app, /error === "vad-unavailable"[\s\S]{0,120}vadAvailable\.value = false;\s*void serverAsr\.start\(\);/);
});

test("a denied microphone is reported as such, not as a VAD failure", () => {
  // 權限被拒換引擎也沒用；當成 VAD 壞掉會白白退到按鍵錄音再被拒一次。
  assert.match(vadRecognizerSource, /NotAllowedError/);
  const denied = vadRecognizerSource.slice(
    vadRecognizerSource.indexOf("if (denied)"),
    vadRecognizerSource.indexOf("return false", vadRecognizerSource.indexOf("if (denied)")),
  );
  assert.ok(denied.indexOf("'not-allowed'") < denied.indexOf("this._supported = false"));
});

test("stopping while the model is still loading cancels the pending start", () => {
  assert.match(vadRecognizerSource, /const mine = \+\+this\.generation/);
  // 載完發現這一輪已經被停掉：pause 而不是開始收音。
  assert.match(vadRecognizerSource, /await instance\.start\(\)\s*if \(mine !== this\.generation/);
});

test("the VAD instance is built once and reused across presses", () => {
  // 每次按鍵都 destroy 再 new 的話，第一次一兩秒、之後幾百毫秒，開頭的字都漏掉。
  assert.match(vadRecognizerSource, /if \(this\.vadReady\) return this\.vadReady/);
  assert.match(vadRecognizerSource, /startOnLoad: false/);
  const stopFn = vadRecognizerSource.slice(
    vadRecognizerSource.indexOf("public stop(): void"),
    vadRecognizerSource.indexOf("public pause(): void"),
  );
  assert.match(stopFn, /current\?\.pause\(\)/);
  // 只比對程式碼，註解裡提到 destroy 沒關係。
  assert.doesNotMatch(stopFn.replace(/\/\/.*$/gm, ""), /destroy/);
  // 只有整個元件卸載才 destroy。
  const disposeFn = vadRecognizerSource.slice(vadRecognizerSource.indexOf("public dispose(): void"));
  assert.match(disposeFn, /instance\.destroy\(\)/);
});

test("starting is reported separately so the UI can say the mic is not live yet", () => {
  assert.match(source, /isStarting: readonly\(isStarting\)/);
  assert.match(source, /onStartingChange:\s*\(val\) => \{\s*isStarting\.value = val/);
  const startFn = vadRecognizerSource.slice(
    vadRecognizerSource.indexOf("public async start()"),
    vadRecognizerSource.indexOf("public stop()"),
  );
  assert.ok(startFn.indexOf("await instance.start()") < startFn.indexOf("this.setListening(true)"));
});

test("useVadAsr reactive refs update on recognizer state changes", async () => {
  let lastOptions = null;
  class MockVadRecognizer {
    constructor(options) {
      lastOptions = options;
      this.supported = true;
    }
    start() {
      lastOptions?.onStartingChange?.(true);
      lastOptions?.onStartingChange?.(false);
      lastOptions?.onListeningChange?.(true);
      return Promise.resolve(true);
    }
    stop() {
      lastOptions?.onListeningChange?.(false);
    }
    pause() { this.stop(); }
    resume() {}
    dispose() {
      lastOptions?.onListeningChange?.(false);
      lastOptions?.onStartingChange?.(false);
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

  const transformed = transformSync(source, {
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
      const VadRecognizer = globalThis.__MockVadRecognizer;
    `)
    .replace(/import\s+{[^}]*}\s+from\s+['"]\.\.\/api\/http['"];?/, `
      const apiFetch = () => Promise.resolve(new Response("{}"));
      const parseJson = () => Promise.resolve({});
    `);

  globalThis.__mockVue = mockVue;
  globalThis.__MockVadRecognizer = MockVadRecognizer;

  const dataUri = `data:text/javascript;base64,${Buffer.from(patched).toString("base64")}`;
  const { useVadAsr } = await import(dataUri);

  const asr = useVadAsr();
  assert.equal(asr.isListening.value, false);
  assert.equal(asr.isStarting.value, false);

  await asr.start();
  assert.equal(asr.isListening.value, true);
  assert.equal(asr.isStarting.value, false);

  asr.stop();
  assert.equal(asr.isListening.value, false);
});
