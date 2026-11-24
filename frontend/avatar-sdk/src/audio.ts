import { OpenVmanAvatarError } from "./errors";
import type { AvatarRuntime } from "./runtime";
import type { OpenVmanAvatarAudioOutput } from "./types";

const PCM_SAMPLE_RATE = 16000;
const PCM_CHUNK_SAMPLES = 4096;
export const DEFAULT_AUDIO_LEAD_MS = 150;
// 照播放速度送 PCM 時，下一包常在上一包播完後才到；給這段寬限，不要每個空檔都
// 清掉嘴型緩衝、結束說話。
const IDLE_GRACE_MS = 300;

interface ScheduledPlay {
  onended: (() => void) | null;
  stop(): void;
}

/**
 * Where scheduled audio is timed. speaker plays through Web Audio; silent
 * keeps the same timeline on the page clock, so a window nobody has clicked
 * can still drive lip sync (browsers suspend AudioContext until a gesture).
 */
interface AudioPlayer {
  now(): number;
  prepare(): Promise<void>;
  decode(encoded: ArrayBuffer): Promise<AudioBuffer>;
  pcmBuffer(samples: Float32Array<ArrayBuffer>): AudioBuffer | number;
  play(buffer: AudioBuffer | number, startTime: number): ScheduledPlay;
  close(): void;
}

export class AvatarAudio {
  private readonly player: AudioPlayer;
  private destroyed = false;
  private nextStartTime = 0;
  private playbackGeneration = 0;
  // 讓排隊中的片段依呼叫順序解碼、排上時間軸。
  private settlers = new Set<() => void>();
  private sources = new Set<ScheduledPlay>();
  private speaking = false;
  // pushPcm 一段話的開頭先扣住 leadMs，一次送進 runtime 再開始播：嘴型模型需要往後看
  // 一段音訊，只有一小包時張不開嘴。
  private held: Int16Array[] = [];
  private leadTimer: number | null = null;
  private idleTimer: number | null = null;
  private speakingTimer: number | null = null;
  private utteranceOpen = false;
  private idleWaiters = new Set<() => void>();

  constructor(
    private readonly runtime: AvatarRuntime,
    private readonly onSpeakingChange: (speaking: boolean) => void,
    audioOutput: OpenVmanAvatarAudioOutput = "speaker",
    private readonly leadMs: number = DEFAULT_AUDIO_LEAD_MS,
  ) {
    this.player = audioOutput === "silent" ? new ClockPlayer() : new WebAudioPlayer();
  }

  async prepare(): Promise<void> {
    await this.player.prepare();
  }

  async playAudio(source: Blob | ArrayBuffer): Promise<void> {
    this.interrupt();
    const generation = this.playbackGeneration;
    if (this.destroyed) return;
    // 先在使用者手勢內恢復 AudioContext，再去等 Blob 讀完。
    await this.prepare();
    if (generation !== this.playbackGeneration || this.destroyed) return;
    const encoded = typeof (source as Blob).arrayBuffer === "function"
      ? await (source as Blob).arrayBuffer()
      : source as ArrayBuffer;
    const scheduled = await this.decodeAndSchedule(encoded, generation);
    if (scheduled) await this.untilFinished(scheduled);
  }

  private async decodeAndSchedule(
    encoded: ArrayBuffer,
    generation: number,
  ): Promise<ScheduledSource | null> {
    const stale = () =>
      generation !== this.playbackGeneration || this.destroyed;
    if (stale()) return null;
    await this.prepare();
    if (stale()) return null;
    const decoded = await this.player.decode(encoded);
    if (stale()) return null;
    this.runtime.beginSpeaking();
    for (const chunk of decodedAudioBufferToPcmChunks(decoded)) {
      this.runtime.pushAudio(chunk);
    }
    return this.scheduleSource(decoded, decoded.length / decoded.sampleRate);
  }

  private untilFinished(scheduled: ScheduledSource): Promise<void> {
    return new Promise<void>((resolve) => {
      const settle = () => {
        this.settlers.delete(settle);
        resolve();
      };
      this.settlers.add(settle);
      scheduled.onFinished(settle);
    });
  }

  async pushPcm(chunk: Int16Array): Promise<void> {
    if (this.destroyed || chunk.length === 0) return;
    await this.prepare();
    if (this.destroyed) return;
    this.cancelIdle();
    if (this.leadMs > 0 && (this.leadTimer !== null || !this.utteranceOpen)) {
      this.held.push(chunk);
      if (this.leadTimer === null) {
        const generation = this.playbackGeneration;
        this.leadTimer = window.setTimeout(() => {
          this.leadTimer = null;
          const held = this.held;
          this.held = [];
          if (generation !== this.playbackGeneration || this.destroyed) return;
          for (const pending of held) this.startPcm(pending);
        }, this.leadMs);
      }
      return;
    }
    this.startPcm(chunk);
  }

  /**
   * Resolves once nothing is scheduled or held back any more (or playback is
   * interrupted), so a caller that streamed PCM can wait for it to be heard.
   */
  untilIdle(): Promise<void> {
    if (this.isIdle()) return Promise.resolve();
    return new Promise<void>((resolve) => {
      this.idleWaiters.add(resolve);
    });
  }

  private isIdle(): boolean {
    return this.sources.size === 0 && this.leadTimer === null && this.held.length === 0;
  }

  private settleIdleWaiters(): void {
    const waiters = [...this.idleWaiters];
    this.idleWaiters.clear();
    for (const resolve of waiters) resolve();
  }

  private startPcm(chunk: Int16Array): void {
    this.utteranceOpen = true;
    const samples = new Float32Array(chunk.length);
    for (let index = 0; index < chunk.length; index += 1) {
      samples[index] = chunk[index] < 0
        ? chunk[index] / 32768
        : chunk[index] / 32767;
    }
    this.runtime.beginSpeaking();
    this.runtime.pushAudio(chunk);

    this.scheduleSource(this.player.pcmBuffer(samples), chunk.length / PCM_SAMPLE_RATE);
  }

  private scheduleSource(
    buffer: AudioBuffer | number,
    durationSeconds: number,
  ): ScheduledSource {
    let listener: (() => void) | null = null;
    let finished = false;
    let playback: ScheduledPlay | null = null;
    const finish = () => {
      finished = true;
      if (playback) this.sources.delete(playback);
      this.finishIfIdle();
      listener?.();
    };
    try {
      this.cancelIdle();
      const startTime = Math.max(this.player.now(), this.nextStartTime);
      this.announceSpeakingAt(startTime);
      playback = this.player.play(buffer, startTime);
      this.sources.add(playback);
      playback.onended = finish;
      this.nextStartTime = startTime + durationSeconds;
    } catch (error) {
      if (playback) this.sources.delete(playback);
      this.finishIfIdle();
      throw error;
    }
    return {
      // 片段可能在呼叫端掛上 listener 前就播完了。
      onFinished: (next) => {
        if (finished) next();
        else listener = next;
      },
    };
  }

  interrupt(): void {
    this.playbackGeneration += 1;
    this.held = [];
    this.utteranceOpen = false;
    for (const timer of [this.leadTimer, this.idleTimer, this.speakingTimer]) {
      if (timer !== null) window.clearTimeout(timer);
    }
    this.leadTimer = null;
    this.idleTimer = null;
    this.speakingTimer = null;
    for (const source of this.sources) {
      source.onended = null;
      source.stop();
    }
    this.sources.clear();
    this.nextStartTime = this.player.now();
    for (const settle of [...this.settlers]) settle();
    this.runtime.clearAudio();
    this.runtime.resetSpeaking();
    this.setSpeaking(false);
    this.settleIdleWaiters();
  }

  destroy(): void {
    this.destroyed = true;
    this.interrupt();
    this.player.close();
  }

  private finishIfIdle(): void {
    if (this.sources.size > 0 || this.idleTimer !== null) return;
    const finish = (): void => {
      this.idleTimer = null;
      if (this.sources.size > 0 || this.leadTimer !== null) return;
      this.utteranceOpen = false;
      if (this.speakingTimer !== null) window.clearTimeout(this.speakingTimer);
      this.speakingTimer = null;
      this.runtime.clearAudio();
      this.runtime.endSpeaking();
      this.setSpeaking(false);
      this.settleIdleWaiters();
    };
    if (this.leadMs > 0) this.idleTimer = window.setTimeout(finish, IDLE_GRACE_MS);
    else finish();
  }

  private cancelIdle(): void {
    if (this.idleTimer === null) return;
    window.clearTimeout(this.idleTimer);
    this.idleTimer = null;
  }

  // speaking start 在第一段音訊真正開始播的時間點才發，不是排上時間軸的當下。
  private announceSpeakingAt(startTime: number): void {
    if (this.speaking || this.speakingTimer !== null) return;
    const delayMs = (startTime - this.player.now()) * 1000;
    if (delayMs <= 5) {
      this.setSpeaking(true);
      return;
    }
    this.speakingTimer = window.setTimeout(() => {
      this.speakingTimer = null;
      this.setSpeaking(true);
    }, delayMs);
  }

  private setSpeaking(speaking: boolean): void {
    if (this.speaking === speaking) return;
    this.speaking = speaking;
    this.onSpeakingChange(speaking);
  }
}

interface ScheduledSource {
  onFinished: (listener: () => void) => void;
}

function audioContextConstructor(): typeof AudioContext {
  const constructor = window.AudioContext
    ?? (window as Window & { webkitAudioContext?: typeof AudioContext })
      .webkitAudioContext;
  if (!constructor) {
    throw new OpenVmanAvatarError(
      "AUTOPLAY_BLOCKED",
      "This browser does not support Web Audio.",
    );
  }
  return constructor;
}

class WebAudioPlayer implements AudioPlayer {
  private context: AudioContext | null = null;

  now(): number {
    return this.context?.currentTime ?? 0;
  }

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

  decode(encoded: ArrayBuffer): Promise<AudioBuffer> {
    return this.ensureContext().decodeAudioData(encoded);
  }

  pcmBuffer(samples: Float32Array<ArrayBuffer>): AudioBuffer {
    const buffer = this.ensureContext().createBuffer(1, samples.length, PCM_SAMPLE_RATE);
    buffer.copyToChannel(samples, 0);
    return buffer;
  }

  play(buffer: AudioBuffer | number, startTime: number): ScheduledPlay {
    const context = this.ensureContext();
    const source = context.createBufferSource();
    source.buffer = buffer as AudioBuffer;
    source.connect(context.destination);
    const scheduled: ScheduledPlay = {
      onended: null,
      stop: () => {
        source.onended = null;
        try {
          source.stop();
        } catch {
          void 0;
        }
      },
    };
    source.onended = () => scheduled.onended?.();
    source.start(startTime);
    return scheduled;
  }

  close(): void {
    void this.context?.close();
    this.context = null;
  }

  private ensureContext(): AudioContext {
    this.context ??= new (audioContextConstructor())({ sampleRate: PCM_SAMPLE_RATE });
    return this.context;
  }
}

/**
 * silent 模式不出聲，只需要「這段什麼時候播完」；用頁面時鐘排程就好，不必向瀏覽器
 * 要音訊權限。整段音檔（playAudio／ask）用 OfflineAudioContext 解碼，它不受自動播放
 * 限制。時間軸跟 speaker 相同：一段接一段，從呼叫當下開始排。
 */
class ClockPlayer implements AudioPlayer {
  now(): number {
    return performance.now() / 1000;
  }

  async prepare(): Promise<void> {}

  decode(encoded: ArrayBuffer): Promise<AudioBuffer> {
    const Offline = window.OfflineAudioContext
      ?? (window as Window & { webkitOfflineAudioContext?: typeof OfflineAudioContext })
        .webkitOfflineAudioContext;
    if (!Offline) {
      throw new OpenVmanAvatarError(
        "AUDIO_PLAYBACK_FAILED",
        "This browser cannot decode audio without Web Audio.",
      );
    }
    return new Offline(1, 1, PCM_SAMPLE_RATE).decodeAudioData(encoded);
  }

  pcmBuffer(samples: Float32Array<ArrayBuffer>): number {
    return samples.length / PCM_SAMPLE_RATE;
  }

  play(buffer: AudioBuffer | number, startTime: number): ScheduledPlay {
    const duration = typeof buffer === "number" ? buffer : buffer.length / buffer.sampleRate;
    const scheduled: ScheduledPlay = {
      onended: null,
      stop: () => window.clearTimeout(timer),
    };
    const endsInMs = Math.max(0, (startTime + duration - this.now()) * 1000);
    const timer = window.setTimeout(() => scheduled.onended?.(), endsInMs);
    return scheduled;
  }

  close(): void {}
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
