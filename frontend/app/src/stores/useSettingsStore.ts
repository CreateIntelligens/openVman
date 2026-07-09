import { reactive, watch } from "vue"
import {
  normalizeAvatarBackgroundFit,
  normalizeAvatarBackgroundId,
} from "../types/avatarBackground"
import { STORAGE_KEYS, readPref, writePref } from "../utils/storageUtils"

function normalizeAvatarRenderMode(value: string): '2d' | '3d' {
  return value === '3d' ? '3d' : '2d'
}

function normalizeCameraPreviewScale(value: string): number {
  const scale = Number.parseFloat(value)
  if (!Number.isFinite(scale)) return 1
  return Math.min(1.35, Math.max(0.85, scale))
}

const state = reactive({
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
})

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

export function useSettingsStore() {
  return state
}
