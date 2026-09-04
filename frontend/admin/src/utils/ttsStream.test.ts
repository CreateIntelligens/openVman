import { describe, expect, it, vi } from "vitest";

import {
  buildWavFile,
  isPcmStreamContentType,
  pcm16ToAudioBuffer,
  playPcmStream,
  streamSampleRate,
} from "./ttsStream";

function fakeContext(sampleRateHint = 48000) {
  const started: { buffer: AudioBuffer; at: number }[] = [];
  const counters = { disconnected: 0 };
  const context = {
    currentTime: 0,
    state: "running",
    destination: { id: "destination" },
    createBuffer: (channels: number, length: number, sampleRate: number) => {
      const data = new Float32Array(length);
      return {
        numberOfChannels: channels,
        length,
        sampleRate,
        duration: length / sampleRate,
        getChannelData: () => data,
      } as unknown as AudioBuffer;
    },
    createBufferSource: () => {
      const source = {
        buffer: null as AudioBuffer | null,
        onended: null as null | (() => void),
        connect: vi.fn(),
        disconnect: vi.fn(() => {
          counters.disconnected += 1;
        }),
        start: vi.fn((at: number) => {
          started.push({ buffer: source.buffer!, at });
          queueMicrotask(() => source.onended?.());
        }),
        stop: vi.fn(),
      };
      return source;
    },
  } as unknown as AudioContext;
  return {
    context,
    started,
    sampleRateHint,
    get disconnected() {
      return counters.disconnected;
    },
  };
}

function streamResponse(chunks: Uint8Array[], contentType = "audio/wav; rate=48000"): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      controller.close();
    },
  });
  return new Response(body, { headers: { "Content-Type": contentType } });
}

describe("ttsStream helpers", () => {
  it("recognises PCM stream content types and their sample rate", () => {
    expect(isPcmStreamContentType("audio/wav; rate=48000")).toBe(true);
    expect(isPcmStreamContentType("audio/pcm;rate=24000")).toBe(true);
    expect(isPcmStreamContentType("audio/mpeg")).toBe(false);
    expect(streamSampleRate("audio/wav; rate=48000", 16000)).toBe(48000);
    expect(streamSampleRate("audio/wav", 16000)).toBe(16000);
  });

  it("converts little-endian PCM16 into normalised floats", () => {
    const { context } = fakeContext();
    const pcm = new Uint8Array(new Int16Array([32767, -32768, 0]).buffer);
    const buffer = pcm16ToAudioBuffer(context, pcm, 48000);
    const data = buffer.getChannelData(0);
    expect(data[0]).toBeCloseTo(1);
    expect(data[1]).toBeCloseTo(-1);
    expect(data[2]).toBe(0);
  });

  it("builds a WAV file whose header matches the data length", () => {
    const wav = buildWavFile(new Uint8Array(400), 48000);
    const view = new DataView(wav);
    expect(wav.byteLength).toBe(444);
    expect(view.getUint32(40, true)).toBe(400);
    expect(view.getUint32(24, true)).toBe(48000);
  });
});

describe("playPcmStream", () => {
  it("strips the WAV header, schedules chunks back to back, and returns a replayable WAV", async () => {
    const { context, started } = fakeContext();
    const header = new Uint8Array(44);
    const pcmA = new Uint8Array(new Int16Array(4800).fill(1000).buffer);
    const pcmB = new Uint8Array(new Int16Array(2400).fill(-1000).buffer);
    const chunks: AudioBuffer[] = [];

    const playback = playPcmStream(streamResponse([header, pcmA, pcmB]), context, {
      minChunkBytes: 1,
      onChunk: (buffer) => chunks.push(buffer),
    });
    const wav = await playback.done;

    expect(started.map((s) => s.buffer.length)).toEqual([4800, 2400]);
    expect(started[1].at).toBeCloseTo(4800 / 48000);
    expect(chunks).toHaveLength(2);
    expect(wav.byteLength).toBe(44 + pcmA.byteLength + pcmB.byteLength);
  });

  it("keeps 16-bit framing when a chunk arrives with an odd byte count", async () => {
    // 網路切割不保證落在 sample 邊界。丟掉落單的位元組會讓後面每個 chunk 的
    // 高低位元組交換，聲音變成爆音——第一段正常、之後全壞就是這個症狀。
    const { context, started } = fakeContext();
    const header = new Uint8Array(44);
    const full = new Int16Array([100, 200, 300, 400, 500, 600]);
    const raw = new Uint8Array(full.buffer);
    // 切在奇數位置：第一段 5 個位元組，第二段 7 個。
    const partA = raw.slice(0, 5);
    const partB = raw.slice(5);

    const playback = playPcmStream(streamResponse([header, partA, partB]), context, {
      minChunkBytes: 1,
    });
    const wav = await playback.done;

    // 播出去的樣本總數必須等於原始樣本數，一個都不能少。
    const playedSamples = started.reduce((sum, s) => sum + s.buffer.length, 0);
    expect(playedSamples).toBe(full.length);
    // 重組出來的 WAV 必須逐位元組等於原始 PCM。
    expect(new Uint8Array(wav.slice(44))).toEqual(raw);
  });

  it("stop() halts scheduled sources and settles the promise", async () => {
    const { context } = fakeContext();
    const body = new ReadableStream<Uint8Array>({ start() { /* never closes */ } });
    const response = new Response(body, { headers: { "Content-Type": "audio/wav; rate=48000" } });

    const playback = playPcmStream(response, context, { minChunkBytes: 1 });
    playback.stop();

    await expect(playback.done).resolves.toBeInstanceOf(ArrayBuffer);
  });
});

describe("playPcmStream resource cleanup", () => {
  it("disconnects each source after it finishes, not only on stop()", async () => {
    // 每段語音都會排很多個 source；播完不斷開的話，輸出節點會一直累積。
    const fake = fakeContext();
    const { context } = fake;
    const header = new Uint8Array(44);
    const pcm = new Uint8Array(new Int16Array(2400).fill(500).buffer);

    const playback = playPcmStream(streamResponse([header, pcm, pcm]), context, {
      minChunkBytes: 1,
    });
    await playback.done;

    expect(fake.disconnected).toBe(2);
  });
});
