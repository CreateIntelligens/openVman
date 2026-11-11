import type { AvatarEngine } from '../../../shared/avatar-engine/index.mjs'
export type OpenVmanAvatarRuntimeInstance = AvatarEngine
export interface OpenVmanAvatarRuntimeConfig { runtimeBaseUrl: string }
declare global {
  interface Window { characterVideo?: HTMLVideoElement }
}
