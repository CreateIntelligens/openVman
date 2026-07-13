import { OpenVmanAvatarError } from "./errors";
import type { AvatarRuntime } from "./runtime";

const PCM_SAMPLE_RATE = 16000;
const PCM_CHUNK_SAMPLES = 4096;

export class AvatarAudio {
  private context: AudioContext | null = null;
  private destroyed = false;
  private playbackGeneration = 0;
  private settlePlayback: (() => void) | null = null;
  private source: AudioBufferSourceNode | null = null;

  constructor(private readonly runtime: AvatarRuntime) {}

  async prepare(): Promise<void> {
    const context = this.ensureContext();
    if (context.state === "suspended") await context.resume();
    if (context.state !== "running") {
      throw new OpenVmanAvatarError(
        "AUTOPLAY_BLOCKED",
        "Audio playback requires a user gesture.",
      );
    }
  }

  async speak(response: Response): Promise<void> {
    const generation = this.playbackGeneration;
    if (this.destroyed) return;
    const context = this.ensureContext();
    await this.prepare();
    if (generation !== this.playbackGeneration || this.destroyed) return;

    const decoded = await context.decodeAudioData(await response.arrayBuffer());
    if (generation !== this.playbackGeneration || this.destroyed) return;
    for (const chunk of decodedAudioBufferToPcmChunks(decoded)) {
      this.runtime.pushAudio(chunk);
    }

    await new Promise<void>((resolve, reject) => {
      const source = context.createBufferSource();
      this.source = source;
      source.buffer = decoded;
      source.connect(context.destination);
      const finish = () => {
        if (this.source === source) this.source = null;
        if (this.settlePlayback === finish) this.settlePlayback = null;
        this.runtime.clearAudio();
        resolve();
      };
      this.settlePlayback = finish;
      source.onended = finish;
      try {
        source.start();
      } catch (error) {
        this.settlePlayback = null;
        this.source = null;
        reject(error);
      }
    });
  }

  interrupt(): void {
    this.playbackGeneration += 1;
    const source = this.source;
    this.source = null;
    if (source) {
      source.onended = null;
      try {
        source.stop();
      } catch {
        void 0;
      }
    }
    const settle = this.settlePlayback;
    this.settlePlayback = null;
    if (settle) settle();
    else this.runtime.clearAudio();
  }

  destroy(): void {
    this.destroyed = true;
    this.interrupt();
    void this.context?.close();
    this.context = null;
  }

  private ensureContext(): AudioContext {
    const AudioContextConstructor = window.AudioContext
      ?? (window as Window & { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext;
    if (!AudioContextConstructor) {
      throw new OpenVmanAvatarError(
        "AUTOPLAY_BLOCKED",
        "This browser does not support Web Audio.",
      );
    }
    this.context ??= new AudioContextConstructor({ sampleRate: PCM_SAMPLE_RATE });
    return this.context;
  }
}

export function decodedAudioBufferToPcmChunks(
  audioBuffer: AudioBuffer,
): Int16Array[] {
  if (audioBuffer.length === 0 || audioBuffer.sampleRate <= 0) return [];

  const channels = Array.from(
    { length: Math.max(1, audioBuffer.numberOfChannels) },
    (_, index) => audioBuffer.getChannelData(index),
  );
  const outputLength = Math.max(
    1,
    Math.round(audioBuffer.length * PCM_SAMPLE_RATE / audioBuffer.sampleRate),
  );
  const output = new Int16Array(outputLength);

  for (let index = 0; index < outputLength; index += 1) {
    const sourcePosition = index * audioBuffer.sampleRate / PCM_SAMPLE_RATE;
    let mixed = 0;
    for (const channel of channels) mixed += interpolate(channel, sourcePosition);
    const sample = Math.max(-1, Math.min(1, mixed / channels.length));
    output[index] = sample < 0
      ? Math.round(sample * 32768)
      : Math.round(sample * 32767);
  }

  const chunks: Int16Array[] = [];
  for (let offset = 0; offset < output.length; offset += PCM_CHUNK_SAMPLES) {
    chunks.push(output.slice(offset, offset + PCM_CHUNK_SAMPLES));
  }
  return chunks;
}

function interpolate(samples: Float32Array, position: number): number {
  const lower = Math.min(Math.floor(position), samples.length - 1);
  const upper = Math.min(lower + 1, samples.length - 1);
  const ratio = position - lower;
  return samples[lower] + (samples[upper] - samples[lower]) * ratio;
}
