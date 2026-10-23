import type { MotionSegment } from '../../../shared/avatar/motion/motion-controller.js'

export type AvatarMotionState = 'idle' | 'thinking' | 'speaking' | 'greeting' | 'bye'
export type AvatarMotionGesture = 'greeting' | 'bye'

// The second project id is kept separate so rollout scope can be reviewed without changing playback.
export const HCIOT_MOTION_PROJECT_IDS: readonly string[] = [
  'proj-9c042e94e0',
  'proj-b85afb8bb6',
]
export const HCIOT_MOTION_CHARACTER_ID = 'hciot-motion'
export const HCIOT_MOTION_VERSION = 'hciot-v1'
export const HCIOT_MOTION_SEGMENTS: Record<AvatarMotionState, MotionSegment> = {
  idle: { start: 0, end: 8 },
  thinking: { start: 8, end: 16 },
  speaking: { start: 0, end: 8 },
  greeting: { start: 16, end: 24, loop: false, next: 'idle' },
  bye: { start: 24, end: 32, loop: false, next: 'idle' },
}

export function hasAvatarMotionProfile(characterId: string, projectId?: string): boolean {
  return characterId === HCIOT_MOTION_CHARACTER_ID
    && Boolean(projectId && HCIOT_MOTION_PROJECT_IDS.includes(projectId))
}

export function validateAvatarMotionManifest(value: unknown): void {
  const manifest = value as {
    id?: string; fps?: number; frameCount?: number; width?: number; height?: number;
    segments?: Record<string, { start?: number; end?: number }>;
  } | null
  if (manifest?.id !== HCIOT_MOTION_VERSION || manifest.fps !== 25
    || manifest.frameCount !== 800 || manifest.width !== 1080 || manifest.height !== 1920) {
    throw new Error('HCIOT 動作素材版本或影片規格不符')
  }
  for (const state of ['idle', 'thinking', 'greeting', 'bye'] as const) {
    const actual = manifest.segments?.[state], expected = HCIOT_MOTION_SEGMENTS[state]
    if (actual?.start !== expected.start || actual?.end !== expected.end) {
      throw new Error(`HCIOT 動作素材 ${state} 時間軸不符`)
    }
  }
}
