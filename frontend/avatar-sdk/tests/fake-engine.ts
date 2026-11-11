// 僅由 Vite test mode 替換共享引擎；正式交付不含此測試替身。
export class AvatarEngine {
  readonly audioContext: AudioContext;
  readonly video: HTMLVideoElement;
  private sources = new Set<AudioBufferSourceNode>();
  private waiters = new Set<() => void>();
  private nextStartTime = 0;
  private speaking = false;
  private output: AudioNode;

  constructor(private readonly options: {
    canvas: HTMLCanvasElement;
    video?: HTMLVideoElement;
    runtimeBaseUrl: string;
    audioOutput?: string;
    onSpeakingChange?: (speaking: boolean) => void;
  }) {
    this.audioContext = new window.AudioContext();
    this.video = options.video ?? document.createElement("video");
    this.output = this.audioContext.destination;
    if (options.audioOutput === "silent") {
      const mute = this.audioContext.createGain();
      mute.gain.value = 0;
      mute.connect(this.audioContext.destination);
      this.output = mute;
    }
  }

  static async create(options: ConstructorParameters<typeof AvatarEngine>[0]) {
    const engine = new AvatarEngine(options);
    await fetch(`${options.runtimeBaseUrl}models/audio.onnx`);
    return engine;
  }

  async loadCharacter(baseUrl: string) {
    const response = await fetch(`${baseUrl}/render_data.json.gz`);
    if (!response.ok) throw new Error(`Character data request failed: ${response.status}`);
    this.video.src = `${baseUrl}/01.webm`;
    await new Promise<void>((resolve, reject) => {
      this.video.addEventListener("canplay", () => resolve(), { once: true });
      this.video.addEventListener("error", () => reject(new Error("Video load failed")), { once: true });
      this.video.load();
    });
    await this.video.play();
  }

  async prepare() {
    if (this.audioContext.state === "suspended") await this.audioContext.resume();
  }

  async appendPcm(pcm: Int16Array) {
    const source = this.audioContext.createBufferSource();
    source.buffer = this.audioContext.createBuffer(1, pcm.length, 16000);
    source.connect(this.output);
    this.sources.add(source);
    this.setSpeaking(true);
    source.onended = () => {
      this.sources.delete(source);
      if (!this.sources.size) {
        this.setSpeaking(false);
        for (const resolve of this.waiters) resolve();
        this.waiters.clear();
      }
    };
    source.start(this.nextStartTime);
    this.nextStartTime += pcm.length / 16000;
  }

  async finishAudio() {
    if (!this.sources.size) return;
    await new Promise<void>((resolve) => this.waiters.add(resolve));
  }

  stop() {
    for (const source of this.sources) {
      source.onended = null;
      source.stop();
    }
    this.sources.clear();
    this.nextStartTime = this.audioContext.currentTime;
    for (const resolve of this.waiters) resolve();
    this.waiters.clear();
    this.setSpeaking(false);
    // 只提供測試觀察，不是正式引擎 API。
    (window as unknown as { engineStopped?: () => void }).engineStopped?.();
  }

  dispose() {
    this.stop();
    this.video.remove();
    void this.audioContext.close();
  }

  private setSpeaking(speaking: boolean) {
    if (this.speaking === speaking) return;
    this.speaking = speaking;
    this.options.onSpeakingChange?.(speaking);
  }
}
