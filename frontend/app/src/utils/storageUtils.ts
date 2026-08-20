export const STORAGE_KEYS = {
  TTS_ENGINE: "avatar.tts_engine",
  CHARACTER_ID: "avatar.character_id",
  PROJECT_ID: "avatar.project_id",
  PERSONA_ID: "avatar.persona_id",
  VOICE_MODE: "avatar.voice_mode",
  TTS_VOICE: "avatar.tts_voice",
  BACKGROUND_ID: "avatar.background_id",
  BACKGROUND_URL: "avatar.background_url",
  BACKGROUND_FIT: "avatar.background_fit",
  CAMERA_PREVIEW_SCALE: "avatar.camera_preview_scale",
  RENDER_MODE: "avatar.render_mode",
  VRM_AVATAR_ID: "avatar.vrm_avatar_id",
  LOGIN_MODE: "avatar.login_mode",
} as const

export function readPref(key: string, fallback: string): string {
  if (typeof window === "undefined") return fallback
  return window.localStorage.getItem(key) ?? fallback
}

export function writePref(key: string, value: string): void {
  if (typeof window === "undefined") return
  window.localStorage.setItem(key, value)
}
