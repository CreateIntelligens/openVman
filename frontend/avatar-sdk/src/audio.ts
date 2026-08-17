import { OpenVmanAvatarError } from "./errors";
import type { AvatarRuntime } from "./runtime";

const PCM_SAMPLE_RATE = 16000;
const PCM_CHUNK_SAMPLES = 4096;

export class AvatarAudio {
  private context: AudioContext | null = null;
  private destroyed = false;
  private nextStartTime = 0;
  private playbackGeneration = 0;
  private settlePlayback: (() => void) | null = null;
  private sources = new Set<AudioBufferSourceNode>();
  private speaking = false;

  constructor(
    private readonly runtime: AvatarRuntime,
    private readonly onSpeakingChange: (speaking: boolean) => void,
  ) {}

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

  async playAudio(source: Blob | ArrayBuffer): Promise<void> {
    this.interrupt();
    const generation = this.playbackGeneration;
    if (this.destroyed) return;
    const context = this.ensureContext();
    await this.prepare();
    if (generation !== this.playbackGeneration || this.destroyed) return;

    const encoded = typeof (source as Blob).arrayBuffer === "function"
      ? await (source as Blob).arrayBuffer()
      : source as ArrayBuffer;
    if (generation !== this.playbackGeneration || this.destroyed) return;
    const decoded = await context.decodeAudioData(encoded);
    if (generation !== this.playbackGeneration || this.destroyed) return;
    this.runtime.beginSpeaking();
    for (const chunk of decodedAudioBufferToPcmChunks(decoded)) {
      this.runtime.pushAudio(chunk);
    }

    await new Promise<void>((resolve, reject) => {
      try {
        const { onFinished } = this.scheduleSource(context, decoded);
        this.settlePlayback = () => resolve();
        onFinished(() => {
          if (this.settlePlayback) this.settlePlayback = null;
          resolve();
        });
      } catch (error) {
        reject(error);
      }
    });
  }

  async pushPcm(chunk: Int16Array): Promise<void> {
    if (this.destroyed || chunk.length === 0) return;
    await this.prepare();
    if (this.destroyed) return;

    const context = this.ensureContext();
    const buffer = context.createBuffer(1, chunk.length, PCM_SAMPLE_RATE);
    const samples = new Float32Array(chunk.length);
    for (let index = 0; index < chunk.length; index += 1) {
      samples[index] = chunk[index] < 0
        ? chunk[index] / 32768
        : chunk[index] / 32767;
    }
    buffer.copyToChannel(samples, 0);
    this.runtime.beginSpeaking();
    this.runtime.pushAudio(chunk);

    this.scheduleSource(context, buffer);
  }

  private scheduleSource(
    context: AudioContext,
    buffer: AudioBuffer,
  ): { onFinished: (listener: () => void) => void } {
    const playbackSource = context.createBufferSource();
    this.sources.add(playbackSource);
    playbackSource.buffer = buffer;
    playbackSource.connect(context.destination);
    let listener: (() => void) | null = null;
    const finish = () => {
      this.sources.delete(playbackSource);
      this.finishIfIdle();
      listener?.();
    };
    playbackSource.onended = finish;
    try {
      this.setSpeaking(true);
      const startTime = Math.max(context.currentTime, this.nextStartTime);
      playbackSource.start(startTime);
      this.nextStartTime = startTime + buffer.length / buffer.sampleRate;
    } catch (error) {
      this.sources.delete(playbackSource);
      this.finishIfIdle();
      throw error;
    }
    return { onFinished: (next) => { listener = next; } };
  }

  interrupt(): void {
    this.playbackGeneration += 1;
    for (const source of this.sources) {
      source.onended = null;
      try {
        source.stop();
      } catch {
        void 0;
      }
    }
    this.sources.clear();
    this.nextStartTime = this.context?.currentTime ?? 0;
    const settle = this.settlePlayback;
    this.settlePlayback = null;
    if (settle) settle();
    this.runtime.clearAudio();
    this.runtime.resetSpeaking();
    this.setSpeaking(false);
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

  private finishIfIdle(): void {
    if (this.sources.size > 0) return;
    this.runtime.clearAudio();
    this.runtime.endSpeaking();
    this.setSpeaking(false);
  }

  private setSpeaking(speaking: boolean): void {
    if (this.speaking === speaking) return;
    this.speaking = speaking;
    this.onSpeakingChange(speaking);
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
