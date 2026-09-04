import { reactive, watch } from "vue"
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

const state = reactive(loadState())

/**
 * Rebind preferences to an account and reload them.
 *
 * store 是模組層級單例，在登入完成前就初始化了，所以帳號 id 到手時要重讀一次。
 * 寫入用的 watch 會照常觸發，但因為值本來就來自這個帳號的鍵，等於原樣寫回。
 */
export function bindSettingsToAccount(accountId: string): void {
  if (currentPrefScope() === (accountId || "")) return
  setPrefScope(accountId)
  Object.assign(state, loadState())
}

watch(() => state.ttsProvider, (v) => writePref(STORAGE_KEYS.TTS_ENGINE, v))
watch(() => state.characterId, (v) => writePref(STORAGE_KEYS.CHARACTER_ID, v))
watch(() => state.projectId, (v) => writePref(STORAGE_KEYS.PROJECT_ID, v))
watch(() => state.personaId, (v) => writePref(STORAGE_KEYS.PERSONA_ID, v))
watch(() => state.voiceMode, (v) => writePref(STORAGE_KEYS.VOICE_MODE, v))
watch(() => state.ttsVoice, (v) => writePref(STORAGE_KEYS.TTS_VOICE, v))
watch(() => state.backgroundId, (v) => writePref(STORAGE_KEYS.BACKGROUND_ID, v))
watch(() => state.backgroundUrl, (v) => writePref(STORAGE_KEYS.BACKGROUND_URL, v))
watch(() => state.backgroundFit, (v) => writePref(STORAGE_KEYS.BACKGROUND_FIT, v))
watch(() => state.cameraPreviewScale, (v) => writePref(STORAGE_KEYS.CAMERA_PREVIEW_SCALE, String(v)))
watch(() => state.renderMode, (v) => writePref(STORAGE_KEYS.RENDER_MODE, v))
watch(() => state.vrmAvatarId, (v) => writePref(STORAGE_KEYS.VRM_AVATAR_ID, v))
watch(() => state.replyMode, (v) => writePref(STORAGE_KEYS.REPLY_MODE, v))

export function useSettingsStore() {
  return state
}
