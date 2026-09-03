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
        disconnect: vi.fn(),
        start: vi.fn((at: number) => {
          started.push({ buffer: source.buffer!, at });
          queueMicrotask(() => source.onended?.());
        }),
        stop: vi.fn(),
      };
      return source;
    },
  } as unknown as AudioContext;
  return { context, started, sampleRateHint };
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

  it("stop() halts scheduled sources and settles the promise", async () => {
    const { context } = fakeContext();
    const body = new ReadableStream<Uint8Array>({ start() { /* never closes */ } });
    const response = new Response(body, { headers: { "Content-Type": "audio/wav; rate=48000" } });

    const playback = playPcmStream(response, context, { minChunkBytes: 1 });
    playback.stop();

    await expect(playback.done).resolves.toBeInstanceOf(ArrayBuffer);
  });
});
