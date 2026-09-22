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

async function loadWav() {
  const { code } = transformSync(read("utils/wav.ts"), { loader: "ts", format: "esm" });
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
  // AI 回話時麥克風若還開著，會把喇叭的聲音再收進來。
  const onSpeechEnd = source.slice(source.indexOf("onSpeechEnd:"), source.indexOf("onVADMisfire:"));
  assert.ok(onSpeechEnd.indexOf("stop()") < onSpeechEnd.indexOf("send(audio)"));
});

test("the model is shared with the admin console instead of duplicated", () => {
  assert.match(source, /VAD_ASSET_BASE = '\/admin\/vad\/'/);
});

test("a VAD that cannot load falls back to push-to-talk and starts recording", () => {
  // 模型或 WASM 載不到（內網連不到 CDN）時，使用者按了麥克風不能什麼都沒發生。
  assert.match(source, /options\.onError\?\.\('vad-unavailable'\)/);
  assert.match(app, /error === "vad-unavailable"[\s\S]{0,120}vadAvailable\.value = false;\s*void serverAsr\.start\(\);/);
});

test("a denied microphone is reported as such, not as a VAD failure", () => {
  // 權限被拒換引擎也沒用；當成 VAD 壞掉會白白退到按鍵錄音再被拒一次。
  assert.match(source, /NotAllowedError/);
  const denied = source.slice(source.indexOf("if (denied)"), source.indexOf("return false", source.indexOf("if (denied)")));
  assert.ok(denied.indexOf("'not-allowed'") < denied.indexOf("isSupported.value = false"));
});

test("stopping while the model is still loading cancels the pending start", () => {
  assert.match(source, /const mine = \+\+generation/);
  assert.match(source, /if \(mine !== generation\) \{\s*await instance\.destroy\(\)/);
});
