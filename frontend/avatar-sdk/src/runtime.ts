import { AvatarEngine } from "../../shared/avatar-engine/index.mjs";
import { OpenVmanAvatarError } from "./errors";
import type { OpenVmanAvatarAudioOutput } from "./types";

declare global {
  interface Window {
    characterVideo?: HTMLVideoElement;
  }
}

export class AvatarRuntime {
  private readonly speakingListeners = new Set<(speaking: boolean) => void>();
  private readonly errorListeners = new Set<(error: unknown) => void>();
  private disposed = false;

  private constructor(private readonly engine: AvatarEngine) {}

  static async create(
    baseUrl: string,
    canvas: HTMLCanvasElement,
    audioOutput: OpenVmanAvatarAudioOutput = "speaker",
    runtimeBaseUrl?: string,
  ): Promise<AvatarRuntime> {
    let runtime: AvatarRuntime | undefined;
    const video = document.createElement("video");
    const engine = await AvatarEngine.create({
      canvas,
      video,
      videoSource: () => window.characterVideo ?? video,
      runtimeBaseUrl: runtimeBaseUrl ?? `${baseUrl}/static/sdk/engine/`,
      audioOutput,
      onError: (error) => {
        for (const listener of runtime?.errorListeners ?? []) listener(error);
      },
      onSpeakingChange: (speaking) => {
        for (const listener of runtime?.speakingListeners ?? []) listener(speaking);
      },
    });
    runtime = new AvatarRuntime(engine);
    // 動作預覽沿用此播放器切換快取影片；渲染與音訊仍由共用引擎持有。
    window.characterVideo = engine.video;
    return runtime;
  }

  get audioContext(): AudioContext {
    return this.engine.audioContext;
  }

  async prepare(): Promise<void> {
    try {
      await this.engine.prepare();
    } catch (error) {
      throw new OpenVmanAvatarError(
        "AUTOPLAY_BLOCKED",
        error instanceof Error ? error.message : String(error),
      );
    }
    if (this.audioContext.state !== "running") {
      throw new OpenVmanAvatarError(
        "AUTOPLAY_BLOCKED",
        "Audio playback requires a user gesture.",
      );
    }
  }

  async loadCharacter(characterId: string, assetsBaseUrl: string): Promise<void> {
    await this.engine.loadCharacter(
      `${assetsBaseUrl}/${encodeURIComponent(characterId)}`,
    );
  }

  onSpeakingChange(listener: (speaking: boolean) => void): () => void {
    this.speakingListeners.add(listener);
    return () => this.speakingListeners.delete(listener);
  }

  onError(listener: (error: unknown) => void): () => void {
    this.errorListeners.add(listener);
    return () => this.errorListeners.delete(listener);
  }

  clearAudio(): void {
    this.engine.stop();
  }

  pushAudio(pcm: Int16Array): Promise<void> {
    return this.engine.appendPcm(pcm);
  }

  finishAudio(): Promise<void> {
    return this.engine.finishAudio();
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.engine.dispose();
    this.speakingListeners.clear();
    this.errorListeners.clear();
    if (window.characterVideo === this.engine.video) delete window.characterVideo;
  }
}
