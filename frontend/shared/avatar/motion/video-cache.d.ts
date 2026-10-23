import type { MotionSegment } from './motion-controller.js';

export interface MotionCacheSnapshot {
  hits: number;
  misses: number;
  entries: number;
  maxEntries: number;
  pending: number;
}
export class MotionVideoCache {
  constructor(active: HTMLVideoElement, segments: Record<string, MotionSegment>, options: {
    createVideo: (source: string) => Promise<HTMLVideoElement>;
    maxEntries?: number;
  });
  active: HTMLVideoElement;
  warm(): Promise<void>;
  acquire(state: string, signal: AbortSignal): Promise<{ video: HTMLVideoElement; cacheHit: boolean }>;
  activate(video: HTMLVideoElement, state: string, options?: { deferRefill?: boolean }): void;
  refill(): Promise<void> | undefined;
  snapshot(): MotionCacheSnapshot;
  dispose(options?: { keepActive?: boolean }): void;
}
