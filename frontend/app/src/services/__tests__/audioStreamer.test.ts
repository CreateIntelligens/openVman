import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { AudioChunkPayload, AudioStreamerConfig } from '../audioStreamer';

// ---------------------------------------------------------------------------
// Mocks – AudioStreamer depends on browser APIs (getUserMedia, AudioContext,
// AudioWorklet) that don't exist in Node. We stub them at the minimum level
// needed to exercise the pure-logic paths and lifecycle.
// ---------------------------------------------------------------------------

function createMockMediaStream(): MediaStream {
  const track = { stop: vi.fn(), kind: 'audio' } as unknown as MediaStreamTrack;
  return { getTracks: () => [track] } as unknown as MediaStream;
}

class FakeGainNode {
  gain = { value: 0 };
  connect = vi.fn();
  disconnect = vi.fn();
}

class FakeMediaStreamSourceNode {
  connect = vi.fn();
  disconnect = vi.fn();
}

class FakeScriptProcessorNode {
  onaudioprocess: ((event: { inputBuffer: { getChannelData: (ch: number) => Float32Array } }) => void) | null = null;
  connect = vi.fn();
  disconnect = vi.fn();
}

let fakeScriptProcessor: FakeScriptProcessorNode;

class FakeAudioContext {
  sampleRate = 16000;
  state: AudioContextState = 'running';
  audioWorklet: undefined = undefined; // force ScriptProcessor fallback
  resume = vi.fn().mockResolvedValue(undefined);
  close = vi.fn().mockResolvedValue(undefined);
  createMediaStreamSource = vi.fn().mockReturnValue(new FakeMediaStreamSourceNode());
  createGain = vi.fn().mockReturnValue(new FakeGainNode());
  createScriptProcessor = vi.fn(() => {
    fakeScriptProcessor = new FakeScriptProcessorNode();
    return fakeScriptProcessor;
  });
  destination = {};
}

// Stub globals before importing the module under test
beforeEach(() => {
  fakeScriptProcessor = new FakeScriptProcessorNode();

  Object.defineProperty(globalThis, 'navigator', {
    value: {
      mediaDevices: {
        getUserMedia: vi.fn().mockResolvedValue(createMockMediaStream()),
      },
    },
    configurable: true,
    writable: true,
  });

  (globalThis as Record<string, unknown>).AudioContext = FakeAudioContext;
  (globalThis as Record<string, unknown>).AudioWorkletNode = undefined;

  // btoa polyfill for Node
  if (typeof globalThis.btoa !== 'function') {
    (globalThis as Record<string, unknown>).btoa = (str: string) =>
      Buffer.from(str, 'binary').toString('base64');
  }

  (globalThis as Record<string, unknown>).URL = {
    createObjectURL: vi.fn(() => 'blob:mock'),
    revokeObjectURL: vi.fn(),
  };
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function createAndStartStreamer(
  overrides: Partial<AudioStreamerConfig> = {},
) {
  // Dynamic import so mocks are in place
  const { AudioStreamer } = await import('../audioStreamer');
  const onChunk = vi.fn<any>();
  const streamer = new AudioStreamer({ onChunk, ...overrides });
  await streamer.start();
  return { streamer, onChunk };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('AudioStreamer', () => {
  describe('start / stop lifecycle', () => {
    it('opens microphone and creates audio nodes on start', async () => {
      const { streamer } = await createAndStartStreamer();
      expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledOnce();
      streamer.stop();
    });

    it('is idempotent – calling start twice does not open a second mic', async () => {
      const { streamer } = await createAndStartStreamer();
      await streamer.start(); // second call
      expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledTimes(1);
      streamer.stop();
    });

    it('releases resources on stop', async () => {
      const { streamer } = await createAndStartStreamer();
      streamer.stop();
      // After stop, internal nodes are nulled and tracks stopped
      const stream = await (navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>).mock.results[0].value;
      expect(stream.getTracks()[0].stop).toHaveBeenCalled();
    });

    it('can be started again after stop', async () => {
      const { streamer } = await createAndStartStreamer();
      streamer.stop();
      await streamer.start();
      expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledTimes(2);
      streamer.stop();
    });
  });

  describe('ScriptProcessor fallback', () => {
    it('uses ScriptProcessor when AudioWorklet is not available', async () => {
      const { streamer } = await createAndStartStreamer();
      // FakeAudioContext has audioWorklet=undefined, so ScriptProcessor path is used
      expect(fakeScriptProcessor).toBeDefined();
      expect(fakeScriptProcessor.connect).toHaveBeenCalled();
      streamer.stop();
    });
  });

  describe('chunk emission', () => {
    it('does not emit chunks when streaming is disabled (default)', async () => {
      const { streamer, onChunk } = await createAndStartStreamer();

      // Simulate audio arriving via ScriptProcessor
      const samples = new Float32Array(1600).fill(0.5);
      fakeScriptProcessor.onaudioprocess?.({
        inputBuffer: { getChannelData: () => samples },
      });

      expect(onChunk).not.toHaveBeenCalled();
      streamer.stop();
    });

    it('emits chunks when streaming is enabled and enough samples arrive', async () => {
      const { streamer, onChunk } = await createAndStartStreamer();
      streamer.setStreamingEnabled(true);

      // Default chunk = 100ms at 16kHz = 1600 samples.
      // FakeAudioContext.sampleRate = 16000 → no resampling needed.
      const samples = new Float32Array(1600).fill(0.1);
      fakeScriptProcessor.onaudioprocess?.({
        inputBuffer: { getChannelData: () => samples },
      });

      expect(onChunk).toHaveBeenCalledTimes(1);
      const payload = onChunk.mock.calls[0][0] as any;
      expect(payload.sampleRate).toBe(16000);
      expect(payload.mimeType).toBe('audio/pcm;rate=16000');
      expect(typeof payload.audioBase64).toBe('string');
      expect(payload.audioBase64.length).toBeGreaterThan(0);
      expect(typeof payload.timestamp).toBe('number');

      streamer.stop();
    });

    it('buffers partial samples until chunk threshold', async () => {
      const { streamer, onChunk } = await createAndStartStreamer();
      streamer.setStreamingEnabled(true);

      // Send 800 samples — less than 1600 threshold
      const partial = new Float32Array(800).fill(0.1);
      fakeScriptProcessor.onaudioprocess?.({
        inputBuffer: { getChannelData: () => partial },
      });
      expect(onChunk).not.toHaveBeenCalled();

      // Send another 800 → total 1600, should emit
      fakeScriptProcessor.onaudioprocess?.({
        inputBuffer: { getChannelData: () => partial },
      });
      expect(onChunk).toHaveBeenCalledTimes(1);

      streamer.stop();
    });

    it('flushes remaining samples when streaming is disabled', async () => {
      const { streamer, onChunk } = await createAndStartStreamer();
      streamer.setStreamingEnabled(true);

      const partial = new Float32Array(500).fill(0.1);
      fakeScriptProcessor.onaudioprocess?.({
        inputBuffer: { getChannelData: () => partial },
      });
      expect(onChunk).not.toHaveBeenCalled();

      streamer.setStreamingEnabled(false);
      // Remaining 500 samples flushed as a smaller final chunk
      expect(onChunk).toHaveBeenCalledTimes(1);

      streamer.stop();
    });
  });
});
