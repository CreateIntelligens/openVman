export const STORAGE_KEYS = {
  TTS_ENGINE: "avatar.tts_engine",
  CHARACTER_ID: "avatar.character_id",
  PERSONA_ID: "avatar.persona_id",
} as const

export function readPref(key: string, fallback: string): string {
  if (typeof window === "undefined") return fallback
  return window.localStorage.getItem(key) ?? fallback
}

export function writePref(key: string, value: string): void {
  if (typeof window === "undefined") return
  window.localStorage.setItem(key, value)
}
