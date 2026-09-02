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
}).outputText.replace(
  /import\s*\{\s*apiFetch\s*\}\s*from\s*['"][^'"]+['"];?/,
  "const apiFetch = (url, init) => fetch(url, { ...init, credentials: 'include' });",
);

const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`;
const { useTtsStreamer } = await import(moduleUrl);

function bytesFromInt16(samples) {
  const pcm = new Int16Array(samples);
  return new Uint8Array(pcm.buffer);
}

function streamingWavResponse(samples = [1, 2, 3, 4]) {
  const pcm = bytesFromInt16(samples);
  const bytes = new Uint8Array(44 + pcm.length);
  bytes.set([...Buffer.from("RIFF")], 0);
  bytes.set([...Buffer.from("WAVE")], 8);
  bytes.set([...Buffer.from("data")], 36);
  bytes.set(pcm, 44);
  return new Response(bytes, {
    status: 200,
    headers: { "Content-Type": "audio/wav" },
  });
}

function fullSpeechResponse(samples = [5, 6, 7, 8], contentType = "audio/wav") {
  const pcm = bytesFromInt16(samples);
  const bytes = new Uint8Array(44 + pcm.length);
  bytes.set([...Buffer.from("RIFF")], 0);
  bytes.set([...Buffer.from("WAVE")], 8);
  bytes.set([...Buffer.from("data")], 36);
  bytes.set(pcm, 44);
  return new Response(bytes, {
    status: 200,
    headers: { "Content-Type": contentType },
  });
}

function installFetch(responseFactory) {
  const calls = [];
  const previousFetch = globalThis.fetch;

  globalThis.fetch = async (url, init) => {
    calls.push({
      url: String(url),
      body: JSON.parse(String(init?.body ?? "{}")),
    });
    return responseFactory(url, init);
  };

  return {
    calls,
    restore: () => {
      globalThis.fetch = previousFetch;
    },
  };
}

test("auto provider uses IndexTTS streaming when IndexTTS is available", async () => {
  const fetchMock = installFetch(() => streamingWavResponse());
  const chunks = [];

  try {
    const streamer = useTtsStreamer({
      ttsProviders: () => [
        { id: "auto", name: "自動", default_voice: "", voices: [] },
        { id: "indextts", name: "IndexTTS", default_voice: "hayley", voices: ["hayley"] },
      ],
      onPcmChunk: (pcm) => chunks.push([...pcm]),
    });

    await streamer.speak("你好", { provider: "auto" });

    assert.equal(fetchMock.calls[0].url, "/api/v1/tts/stream");
    assert.deepEqual(fetchMock.calls[0].body, { text: "你好", character: "hayley" });
    assert.deepEqual(chunks, [[1, 2, 3, 4]]);
  } finally {
    fetchMock.restore();
  }
});

test("explicit IndexTTS provider sends the selected voice as character", async () => {
  const fetchMock = installFetch(() => streamingWavResponse());

  try {
    const streamer = useTtsStreamer({
      ttsProviders: () => [
        { id: "indextts", name: "IndexTTS", default_voice: "hayley", voices: ["hayley", "morgan"] },
      ],
      onPcmChunk: () => undefined,
    });

    await streamer.speak("測試", { provider: "indextts", voice: "morgan" });

    assert.equal(fetchMock.calls[0].url, "/api/v1/tts/stream");
    assert.deepEqual(fetchMock.calls[0].body, { text: "測試", character: "morgan" });
  } finally {
    fetchMock.restore();
  }
});

test("gemini-tts uses the streaming endpoint with provider and voice fields", async () => {
  const fetchMock = installFetch(() => streamingWavResponse());

  try {
    const streamer = useTtsStreamer({
      ttsProviders: () => [
        { id: "gemini-tts", name: "Gemini TTS", default_voice: "Kore", voices: ["Kore", "Despina"] },
      ],
      onPcmChunk: () => undefined,
    });

    await streamer.speak("測試", { provider: "gemini-tts", voice: "Despina" });

    assert.equal(fetchMock.calls[0].url, "/api/v1/tts/stream");
    assert.deepEqual(fetchMock.calls[0].body, {
      text: "測試",
      provider: "gemini-tts",
      voice: "Despina",
    });
  } finally {
    fetchMock.restore();
  }
});

test("non-streaming providers continue to use the full speech endpoint", async () => {
  const fetchMock = installFetch(() => fullSpeechResponse());

  try {
    const streamer = useTtsStreamer({
      ttsProviders: () => [
        { id: "indextts", name: "IndexTTS", default_voice: "hayley", voices: ["hayley"] },
        { id: "edge-tts", name: "Edge TTS", default_voice: "zh-TW-HsiaoChenNeural", voices: ["zh-TW-HsiaoChenNeural"] },
      ],
      onPcmChunk: () => undefined,
    });

    await streamer.speak("測試", { provider: "edge-tts", voice: "zh-TW-HsiaoChenNeural" });

    assert.equal(fetchMock.calls[0].url, "/v1/audio/speech");
    assert.deepEqual(fetchMock.calls[0].body, {
      input: "測試",
      provider: "edge-tts",
      voice: "zh-TW-HsiaoChenNeural",
    });
  } finally {
    fetchMock.restore();
  }
});

test("gemini-tts's 24kHz raw PCM stream is resampled to 16kHz across chunk boundaries", async () => {
  // 24kHz PCM ramp, split into two raw chunks (no WAV header) to exercise
  // the streaming resampler's cross-chunk continuity.
  const allSamples = Array.from({ length: 48 }, (_, i) => i * 100);
  const chunk1 = bytesFromInt16(allSamples.slice(0, 24));
  const chunk2 = bytesFromInt16(allSamples.slice(24));

  const fetchMock = installFetch(() => new Response(
    new ReadableStream({
      start(controller) {
        controller.enqueue(chunk1);
        controller.enqueue(chunk2);
        controller.close();
      },
    }),
    { status: 200, headers: { "Content-Type": "audio/l16;rate=24000;channels=1" } },
  ));

  const chunks = [];
  try {
    const streamer = useTtsStreamer({
      ttsProviders: () => [
        { id: "gemini-tts", name: "Gemini TTS", default_voice: "Kore", voices: ["Kore"] },
      ],
      onPcmChunk: (pcm) => chunks.push([...pcm]),
    });

    await streamer.speak("測試", { provider: "gemini-tts", voice: "Kore" });

    const combined = chunks.flat();
    // 48 samples at 24kHz => 2ms; resampled to 16kHz => 32 samples.
    assert.equal(combined.length, 32);
    // Values should stay monotonically increasing (no discontinuity/seam
    // at the chunk boundary introduced by the resampler).
    for (let i = 1; i < combined.length; i++) {
      assert.ok(combined[i] >= combined[i - 1], `sample ${i} decreased: ${combined[i - 1]} -> ${combined[i]}`);
    }
  } finally {
    fetchMock.restore();
  }
});
