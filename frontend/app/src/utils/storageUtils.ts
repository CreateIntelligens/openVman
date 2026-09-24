import {
  setStorageScope,
  readScoped,
  writeScoped,
  removeScoped,
  hasScoped,
  SPEECH_STORAGE_KEYS,
} from "@shared/speech"

export const STORAGE_KEYS = {
  TTS_ENGINE: SPEECH_STORAGE_KEYS.TTS_PROVIDER,
  CHARACTER_ID: "avatar.character_id",
  PROJECT_ID: "avatar.project_id",
  PERSONA_ID: "avatar.persona_id",
  VOICE_MODE: "avatar.voice_mode",
  TTS_VOICE: SPEECH_STORAGE_KEYS.TTS_VOICE,
  BACKGROUND_ID: "avatar.background_id",
  BACKGROUND_URL: "avatar.background_url",
  BACKGROUND_FIT: "avatar.background_fit",
  CAMERA_PREVIEW_SCALE: "avatar.camera_preview_scale",
  RENDER_MODE: "avatar.render_mode",
  VRM_AVATAR_ID: "avatar.vrm_avatar_id",
  REPLY_MODE: "avatar.reply_mode",
  LOGIN_MODE: "avatar.login_mode",
  // 前台臨時關掉的語言分流，依專案分開存：{"proj-x": ["es"]}。
  LANGUAGE_ROUTES_OFF: "avatar.language_routes_off",
} as const

// 目前綁定的帳號。偏好是每個帳號各自一份，共用瀏覽器時才不會把上一個人的
// 人物、專案、角色帶給下一個人。登入前是空字串，此時讀寫的是未綁定的舊鍵值。
let scopeId = ""

/** Bind preference storage to an account; "" unbinds (logged out). */
export function setPrefScope(accountId: string): void {
  scopeId = accountId || ""
  setStorageScope(scopeId)
}

export function currentPrefScope(): string {
  return scopeId
}

function scopedKey(key: string): string {
  return scopeId ? `${key}::${scopeId}` : key
}

export function readPref(key: string, fallback: string): string {
  try {
    const val = readScoped(key, null)
    if (val !== null) return val
    const scoped = window.localStorage.getItem(scopedKey(key))
    if (scoped !== null) return scoped
    return window.localStorage.getItem(key) ?? fallback
  } catch {
    return fallback
  }
}

export function hasPref(key: string): boolean {
  if (hasScoped(key)) return true
  try {
    return window.localStorage.getItem(scopedKey(key)) !== null || window.localStorage.getItem(key) !== null
  } catch {
    return false
  }
}

export function writePref(key: string, value: string): void {
  writeScoped(key, value)
  try {
    window.localStorage.setItem(scopedKey(key), value)
  } catch {
    // 存不下來就算了，下次開啟沿用預設值。
  }
}

/** 清掉這個帳號的偏好，連同未綁定的舊鍵——不然 readPref 的舊值回退會把它復活。 */
export function removePref(key: string): void {
  removeScoped(key)
  try {
    window.localStorage.removeItem(scopedKey(key))
    window.localStorage.removeItem(key)
  } catch {
    // 同上。
  }
}
