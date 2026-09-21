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
  REPLY_MODE: "avatar.reply_mode",
  LOGIN_MODE: "avatar.login_mode",
} as const

// 目前綁定的帳號。偏好是每個帳號各自一份，共用瀏覽器時才不會把上一個人的
// 人物、專案、角色帶給下一個人。登入前是空字串，此時讀寫的是未綁定的舊鍵值。
let scopeId = ""

/** Bind preference storage to an account; "" unbinds (logged out). */
export function setPrefScope(accountId: string): void {
  scopeId = accountId || ""
}

export function currentPrefScope(): string {
  return scopeId
}

function scopedKey(key: string): string {
  return scopeId ? `${key}::${scopeId}` : key
}

// 無痕模式或封鎖網站資料時，localStorage 的存取會直接拋例外（Safari 無痕下
// setItem 是 QuotaExceededError）。寫入是從 store 的 watch() 裡呼叫的，例外會
// 竄進 Vue 的響應式系統，所以這裡一律吞掉——偏好存不下來只是不方便，不該讓
// 整個畫面壞掉。
export function readPref(key: string, fallback: string): string {
  if (typeof window === "undefined") return fallback
  try {
    const scoped = window.localStorage.getItem(scopedKey(key))
    if (scoped !== null) return scoped
    // 這個帳號還沒有自己的值：沿用未綁定的舊值當起點，讓既有使用者升級後
    // 不會突然被重設，但之後的寫入都會落在自己的鍵上。
    return window.localStorage.getItem(key) ?? fallback
  } catch {
    return fallback
  }
}

/** 這個偏好有沒有被存過。有預設值的欄位（例如背景的 "dark"）光看值分不出
 *  「使用者選了 dark」還是「從沒選過」，要用這個判斷。 */
export function hasPref(key: string): boolean {
  if (typeof window === "undefined") return false
  try {
    return window.localStorage.getItem(scopedKey(key)) !== null
      || window.localStorage.getItem(key) !== null
  } catch {
    return false
  }
}

export function writePref(key: string, value: string): void {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(scopedKey(key), value)
  } catch {
    // 存不下來就算了，下次開啟沿用預設值。
  }
}

/** 清掉這個帳號的偏好，連同未綁定的舊鍵——不然 readPref 的舊值回退會把它復活。 */
export function removePref(key: string): void {
  if (typeof window === "undefined") return
  try {
    window.localStorage.removeItem(scopedKey(key))
    window.localStorage.removeItem(key)
  } catch {
    // 同上。
  }
}
