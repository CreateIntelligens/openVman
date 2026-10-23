export interface MotionSegment {
  start: number;
  end: number;
  loop?: boolean;
  next?: string;
}
export interface MotionTransition {
  state: string;
  reason: string;
  cacheHit: boolean;
  prepareMs: number;
  renderMs: number;
  ms: number;
}
export interface MotionPlayerHooks {
  reuseContinuousSegment?: boolean;
  beforeSeek?: (state: string) => void;
  acquireVideo?: (state: string, signal: AbortSignal) => Promise<{ video: HTMLVideoElement; cacheHit: boolean }>;
  activateVideo?: (video: HTMLVideoElement, state: string) => void;
  afterSeek?: (state: string, signal: AbortSignal, video: HTMLVideoElement) => Promise<void>;
  onChange?: (state: string) => void;
  onError?: (error: unknown) => void;
}
export class MotionSegmentPlayer {
  constructor(video: HTMLVideoElement, segments: Record<string, MotionSegment>, hooks?: MotionPlayerHooks);
  video: HTMLVideoElement;
  state: string;
  loops: number;
  transitions: MotionTransition[];
  errors: string[];
  transitioning: boolean;
  disposed: boolean;
  setState(state: string, reason?: string): Promise<boolean>;
  dispose(): void;
}
export function seekVideo(video: HTMLVideoElement, target: number, signal: AbortSignal, timeout?: number): Promise<void>;
export function waitForDecodedFrame(video: HTMLVideoElement, signal: AbortSignal, segment?: MotionSegment): Promise<void>;
