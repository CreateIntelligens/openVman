import type { AvatarRuntime } from "./runtime";

const PCM_SAMPLE_RATE = 16000;
const PCM_CHUNK_SAMPLES = 4096;
const PCM_IDLE_DRAIN_MS = 160;

export class AvatarAudio {
  private destroyed = false;
  private playbackGeneration = 0;
  private queueTail: Promise<void> = Promise.resolve();
  private readonly unsubscribe: () => void;
  private pcmDrainTimer: number | null = null;
  private pcmInputRevision = 0;

  constructor(
    private readonly runtime: AvatarRuntime,
    onSpeakingChange: (speaking: boolean) => void,
    private readonly onError: (error: unknown) => void = () => {},
  ) {
    this.unsubscribe = runtime.onSpeakingChange(onSpeakingChange);
  }

  async prepare(): Promise<void> {
    await this.runtime.prepare();
  }

  async playAudio(source: Blob | ArrayBuffer): Promise<void> {
    this.interrupt();
    const generation = this.playbackGeneration;
    if (this.destroyed) return;
    // 在使用者手勢內恢復唯一的引擎 AudioContext，再等待 Blob。
    await this.prepare();
    if (this.isStale(generation)) return;
    const encoded = typeof (source as Blob).arrayBuffer === "function"
      ? await (source as Blob).arrayBuffer()
      : source as ArrayBuffer;
    await this.decodeAndPlay(encoded, generation);
  }

  async queueAudio(source: ArrayBuffer): Promise<void> {
    this.cancelPcmDrain();
    const generation = this.playbackGeneration;
    const step = this.queueTail.then(() => this.decodeAndPlay(source, generation));
    this.queueTail = step.catch(() => undefined);
    await step;
  }

  private async decodeAndPlay(
    encoded: ArrayBuffer,
    generation: number,
  ): Promise<void> {
    if (this.isStale(generation)) return;
    await this.prepare();
    if (this.isStale(generation)) return;
    const decoded = await this.runtime.audioContext.decodeAudioData(encoded);
    if (this.isStale(generation)) return;
    for (const chunk of decodedAudioBufferToPcmChunks(decoded)) {
      if (this.isStale(generation)) return;
      await this.runtime.pushAudio(chunk);
    }
    if (!this.isStale(generation)) await this.runtime.finishAudio();
  }

  async pushPcm(chunk: Int16Array): Promise<void> {
    if (this.destroyed || chunk.length === 0) return;
    this.cancelPcmDrain();
    const inputRevision = this.pcmInputRevision;
    const generation = this.playbackGeneration;
    await this.prepare();
    if (this.isStale(generation)) return;
    await this.runtime.pushAudio(chunk);
    if (this.isStale(generation) || inputRevision !== this.pcmInputRevision) return;
    // 公開 PCM API 沒有 EOS；短暫閒置後沖出推論尾端，避免嘴型停在 rebuffering。
    this.pcmDrainTimer = window.setTimeout(() => {
      this.pcmDrainTimer = null;
      if (!this.isStale(generation)) {
        void this.runtime.finishAudio().catch((error) => {
          if (!this.isStale(generation)) this.onError(error);
        });
      }
    }, PCM_IDLE_DRAIN_MS);
  }

  interrupt(): void {
    this.playbackGeneration += 1;
    this.cancelPcmDrain();
    // 舊解碼可能尚未結束，新一輪不可被舊 queue 阻擋。
    this.queueTail = Promise.resolve();
    this.runtime.clearAudio();
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    this.interrupt();
    this.unsubscribe();
  }

  private cancelPcmDrain(): void {
    this.pcmInputRevision += 1;
    if (this.pcmDrainTimer === null) return;
    window.clearTimeout(this.pcmDrainTimer);
    this.pcmDrainTimer = null;
  }

  private isStale(generation: number): boolean {
    return this.destroyed || generation !== this.playbackGeneration;
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
