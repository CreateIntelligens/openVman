export interface RenderData {
  schema: 'openvman.render.v2'; frameRate: 25; frameSize: [number, number];
  geometrySource: 'mediapipe-video';
  frames: {region: [number, number, number, number]; outer: number[]; inner: number[]}[];
}
export interface EngineOptions {
  canvas: HTMLCanvasElement;
  video?: HTMLVideoElement;
  videoSource?: () => HTMLVideoElement;
  runtimeBaseUrl: string;
  audioOutput?: 'speaker' | 'silent';
  onSpeakingChange?: (speaking: boolean) => void;
  onError?: (error: Error) => void;
}
export function decodeRenderPayload(bytes: Uint8Array): Promise<RenderData>;
export class AvatarEngine {
  static create(options: EngineOptions): Promise<AvatarEngine>;
  readonly audioContext: AudioContext;
  readonly video: HTMLVideoElement;
  readonly state: string;
  readonly speaking: boolean;
  prepare(): Promise<void>;
  loadCharacter(base: string, options?: {signal?: AbortSignal; payload?: Uint8Array; videoUrl?: string}): Promise<void>;
  applyCharacterData(data: RenderData): void;
  appendPcm(pcm: Int16Array): Promise<void>;
  finishAudio(): Promise<void>;
  stop(): void;
  dispose(): void;
  subscribe(listener: (state: string, previous?: string, details?: Record<string, unknown>) => void): () => void;
  diagnostics(): { state: string; generation: number; speaking: boolean; controls: number[]; sources: number; telemetry: Record<string, unknown>; frame: number };
}
