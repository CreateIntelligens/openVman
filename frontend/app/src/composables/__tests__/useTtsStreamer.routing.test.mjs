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

    assert.equal(fetchMock.calls[0].url, "/tts/stream");
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

    assert.equal(fetchMock.calls[0].url, "/tts/stream");
    assert.deepEqual(fetchMock.calls[0].body, { text: "測試", character: "morgan" });
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
