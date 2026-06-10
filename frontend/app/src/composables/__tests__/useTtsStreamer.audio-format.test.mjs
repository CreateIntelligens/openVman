import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import ts from "typescript";

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../useTtsStreamer.ts"), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ES2022,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText;

const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`;
const {
  audioResponseNeedsDecode,
  decodedAudioBufferToPcmChunks,
  pcmChunksFromAudioBytes,
} = await import(moduleUrl);

function bytesFromInt16(samples) {
  const pcm = new Int16Array(samples);
  return new Uint8Array(pcm.buffer);
}

function wavBytes(samples) {
  const pcm = bytesFromInt16(samples);
  const bytes = new Uint8Array(44 + pcm.length);
  const view = new DataView(bytes.buffer);
  bytes.set([...Buffer.from("RIFF")], 0);
  view.setUint32(4, 36 + pcm.length, true);
  bytes.set([...Buffer.from("WAVE")], 8);
  bytes.set([...Buffer.from("fmt ")], 12);
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, 16000, true);
  view.setUint32(28, 32000, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  bytes.set([...Buffer.from("data")], 36);
  view.setUint32(40, pcm.length, true);
  bytes.set(pcm, 44);
  return bytes;
}

test("encoded speech responses are decoded instead of treated as PCM", () => {
  assert.equal(audioResponseNeedsDecode("audio/mpeg"), true);
  assert.equal(audioResponseNeedsDecode("audio/mp3; charset=binary"), true);
  assert.equal(audioResponseNeedsDecode("audio/wav"), false);
  assert.equal(audioResponseNeedsDecode("audio/pcm"), false);
});

test("raw PCM responses keep the first samples", () => {
  const chunks = pcmChunksFromAudioBytes(bytesFromInt16([1, 2, 3, 4]), "audio/pcm");

  assert.equal(chunks.length, 1);
  assert.deepEqual([...chunks[0]], [1, 2, 3, 4]);
});

test("WAV responses skip the RIFF header and keep PCM data", () => {
  const chunks = pcmChunksFromAudioBytes(wavBytes([10, -10, 20, -20]), "audio/wav");

  assert.equal(chunks.length, 1);
  assert.deepEqual([...chunks[0]], [10, -10, 20, -20]);
});

test("decoded encoded audio is resampled to 16 kHz PCM", () => {
  const fakeBuffer = {
    sampleRate: 32000,
    numberOfChannels: 1,
    length: 4,
    getChannelData: () => new Float32Array([0, 0.5, 1, -0.5]),
  };

  const chunks = decodedAudioBufferToPcmChunks(fakeBuffer, 16000);

  assert.equal(chunks.length, 1);
  assert.equal(chunks[0].length, 2);
  assert.equal(chunks[0][0], 0);
  assert.equal(chunks[0][1], 32767);
});
