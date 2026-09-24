import { reactive } from "vue"
import {
  normalizeAvatarBackgroundFit,
  normalizeAvatarBackgroundId,
} from "../types/avatarBackground"
import { normalizeReplyMode } from "../types/replyMode"
import {
  STORAGE_KEYS,
  currentPrefScope,
  readPref,
  setPrefScope,
  writePref,
} from "../utils/storageUtils"

function normalizeAvatarRenderMode(value: string): '2d' | '3d' {
  return value === '3d' ? '3d' : '2d'
}

function normalizeCameraPreviewScale(value: string): number {
  const scale = Number.parseFloat(value)
  if (!Number.isFinite(scale)) return 1
  return Math.min(1.35, Math.max(0.85, scale))
}

function loadState() {
  return {
    ttsProvider: readPref(STORAGE_KEYS.TTS_ENGINE, "auto"),
    characterId: readPref(STORAGE_KEYS.CHARACTER_ID, ""),
    projectId: readPref(STORAGE_KEYS.PROJECT_ID, "default"),
    personaId: readPref(STORAGE_KEYS.PERSONA_ID, "default"),
    voiceMode: readPref(STORAGE_KEYS.VOICE_MODE, "text") as 'live' | 'text',
    ttsVoice: readPref(STORAGE_KEYS.TTS_VOICE, ""),
    backgroundId: normalizeAvatarBackgroundId(readPref(STORAGE_KEYS.BACKGROUND_ID, "dark")),
    backgroundUrl: readPref(STORAGE_KEYS.BACKGROUND_URL, ""),
    backgroundFit: normalizeAvatarBackgroundFit(readPref(STORAGE_KEYS.BACKGROUND_FIT, "cover")),
    cameraPreviewScale: normalizeCameraPreviewScale(readPref(STORAGE_KEYS.CAMERA_PREVIEW_SCALE, "1")),
    renderMode: normalizeAvatarRenderMode(readPref(STORAGE_KEYS.RENDER_MODE, "2d")),
    vrmAvatarId: readPref(STORAGE_KEYS.VRM_AVATAR_ID, "qqman"),
    replyMode: normalizeReplyMode(readPref(STORAGE_KEYS.REPLY_MODE, "fast")),
  }
}

export type SettingsState = ReturnType<typeof loadState>

const PREF_KEYS: Record<keyof SettingsState, string> = {
  ttsProvider: STORAGE_KEYS.TTS_ENGINE,
  characterId: STORAGE_KEYS.CHARACTER_ID,
  projectId: STORAGE_KEYS.PROJECT_ID,
  personaId: STORAGE_KEYS.PERSONA_ID,
  voiceMode: STORAGE_KEYS.VOICE_MODE,
  ttsVoice: STORAGE_KEYS.TTS_VOICE,
  backgroundId: STORAGE_KEYS.BACKGROUND_ID,
  backgroundUrl: STORAGE_KEYS.BACKGROUND_URL,
  backgroundFit: STORAGE_KEYS.BACKGROUND_FIT,
  cameraPreviewScale: STORAGE_KEYS.CAMERA_PREVIEW_SCALE,
  renderMode: STORAGE_KEYS.RENDER_MODE,
  vrmAvatarId: STORAGE_KEYS.VRM_AVATAR_ID,
  replyMode: STORAGE_KEYS.REPLY_MODE,
}

/*
 * state 是這次實際在用的值，saved 是使用者親手存過的值，兩者刻意分開。
 *
 * 開場載入清單時會暫時清空、清單失敗或選擇失效時會退回帳號預設——這些都只是
 * 「這一次先用這個」，不是使用者的決定。以前用 watch 把 state 的每次變動都寫回
 * localStorage，清單載入失敗一次、或載入到一半就重整，存的選擇就被蓋成空字串或
 * 預設值，使用者的感受是下拉選單每次打開都回到預設。所以只有 saveSettings()
 * （使用者按套用）才寫入；開場挑選一律以 saved 為準，下次開啟會再試一次。
 */
const initial = loadState()
const state = reactive({ ...initial })
let saved: SettingsState = initial

/**
 * Rebind preferences to an account and reload them.
 *
 * store 是模組層級單例，在登入完成前就初始化了，所以帳號 id 到手時要重讀一次。
 */
export function bindSettingsToAccount(accountId: string): void {
  if (currentPrefScope() === (accountId || "")) return
  setPrefScope(accountId)
  saved = loadState()
  Object.assign(state, saved)
}

/** Apply settings the user chose and remember them for next time. */
export function saveSettings(patch: Partial<SettingsState>): void {
  Object.assign(state, patch)
  saved = { ...saved, ...patch }
  for (const field of Object.keys(patch) as (keyof SettingsState)[]) {
    writePref(PREF_KEYS[field], String(patch[field]))
  }
}

/** What the user last saved; bootstrap prefers these over account defaults. */
export function savedSettings(): Readonly<SettingsState> {
  return saved
}

export function useSettingsStore() {
  return state
}
