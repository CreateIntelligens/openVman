import { apiFetch } from '../api/http'
import { createClientId } from './avatarChatTypes'

export type ClientEvent =
  | 'page_open' | 'load_failed' | 'load_retry'
  | 'autoplay_blocked' | 'autoplay_unlocked'
  | 'audio_stalled' | 'audio_recovered' | 'video_stalled' | 'video_recovered'
  | 'reload_offered' | 'reload'

export type BrowserFamily = 'line' | 'facebook' | 'instagram' | 'ios_safari' | 'android' | 'other'

interface ClientVideoState {
  paused: boolean
  ready_state: number
  network_state: number
  current_time: number
  error_code: number | null
}

interface ClientEventFields {
  failure_type?: string
  detail?: string
  project_id?: string
  session_id?: string
  attempt?: number
}

interface ClientEventOptions {
  now?: () => number
  send?: (payload: Record<string, unknown>) => void | Promise<void>
}

export const pageId = createClientId()
const lastReported = new Map<ClientEvent, number>()
let activated = false
let sampling = false
let frameRequest: number | null = null
let sampleStart: number | null = null
let frames = 0
let latestFps: number | null = null

export function markUserActivated(): void {
  activated = true
}

export function userActivated(): boolean {
  return globalThis.navigator?.userActivation?.hasBeenActive ?? activated
}

function sampleFrame(at: number): void {
  if (sampleStart === null) {
    sampleStart = at
  } else {
    frames += 1
    const elapsed = at - sampleStart
    if (elapsed >= 2000) {
      latestFps = Math.min(240, Math.round(frames * 1000 / elapsed))
      sampleStart = at
      frames = 0
    }
  }
  frameRequest = requestAnimationFrame(sampleFrame)
}

function updateSampling(): void {
  if (document.hidden) {
    if (frameRequest !== null) cancelAnimationFrame(frameRequest)
    frameRequest = null
    sampleStart = null
    frames = 0
    latestFps = null
  } else if (frameRequest === null) {
    frameRequest = requestAnimationFrame(sampleFrame)
  }
}

export function startRafSampler(): void {
  if (sampling) return
  sampling = true
  document.addEventListener('visibilitychange', updateSampling)
  updateSampling()
}

export function rafFps(): number | null {
  return globalThis.document?.hidden ? null : latestFps
}

export function videoState(): ClientVideoState | null {
  const video = globalThis.window?.characterVideo
  if (!video) return null
  return {
    paused: video.paused,
    ready_state: video.readyState,
    network_state: video.networkState,
    current_time: Number.isFinite(video.currentTime) ? Math.max(0, video.currentTime) : 0,
    error_code: video.error?.code ?? null,
  }
}

export function browserFamily(ua = globalThis.navigator?.userAgent ?? ''): BrowserFamily {
  if (/Line\//i.test(ua)) return 'line'
  if (/FBAN|FBAV/i.test(ua)) return 'facebook'
  if (/Instagram/i.test(ua)) return 'instagram'
  if (/iPhone|iPad/i.test(ua)) return 'ios_safari'
  if (/Android/i.test(ua)) return 'android'
  return 'other'
}

function sendClientEvent(payload: Record<string, unknown>): void {
  void apiFetch('/api/v1/metrics/client-event', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    keepalive: true,
  }).catch(() => {})
}

export function reportClientEvent(
  event: ClientEvent,
  fields: ClientEventFields = {},
  { now = Date.now, send = sendClientEvent }: ClientEventOptions = {},
): void {
  try {
    const time = now()
    if (event !== 'page_open' && event !== 'reload') {
      const last = lastReported.get(event)
      if (last !== undefined && time - last < 10_000) return
      lastReported.set(event, time)
    }
    const visibility = globalThis.document?.visibilityState
    const detail = fields.detail ?? ''
    const payload = {
      ...fields,
      detail: Array.from(detail).slice(0, 300).join(''),
      event,
      page_id: pageId,
      at: new Date(time).toISOString(),
      user_activated: userActivated(),
      video: videoState(),
      raf_fps: rafFps(),
      visibility: visibility === 'visible' || visibility === 'hidden' ? visibility : '',
      online: globalThis.navigator?.onLine ?? null,
      browser: browserFamily(),
    }
    void Promise.resolve(send(payload)).catch(() => {})
  } catch {
    // 診斷不能打斷原本的操作。
  }
}

export function turnClientState() {
  return {
    user_activated: userActivated(),
    raf_fps: rafFps(),
    video: videoState(),
    failure_type: '',
  }
}
