/**
 * 後台「試用／使用」交給前台的一次性指令。
 *
 * 後台按下按鈕時寫一筆，前台開場載完清單後取走並立刻刪掉，再照「使用者在設定
 * 選了它、按下套用」的路徑處理（會存成這個帳號的偏好）。
 *
 * 刻意不用網址參數：nginx 把 "/" 轉到帶前綴的路徑時會丟掉 query，而且網址
 * 誰都能做一條丟給別人點；同源 localStorage 只有我們自己的頁面寫得進來。
 * 鍵不分帳號作用域：後台與前台綁定作用域的時機不同，寫讀兩邊會對不上，
 * 改由內容裡的 accountId 判斷是不是給這個人的。
 */

export const ADMIN_HANDOFF_KEY = 'avatar.admin_handoff'
export const ADMIN_HANDOFF_MAX_AGE_MS = 120_000

export interface AdminHandoff {
  v: 1
  accountId: string
  projectId?: string
  characterId?: string
  backgroundId?: string
  backgroundUrl?: string
  /** 寫入時間（ms epoch）。 */
  createdAt: number
}

function storage(): Storage | null {
  if (typeof window === 'undefined') return null
  try {
    return window.localStorage
  } catch {
    return null
  }
}

export function writeAdminHandoff(payload: AdminHandoff): void {
  try {
    storage()?.setItem(ADMIN_HANDOFF_KEY, JSON.stringify(payload))
  } catch {
    // 存不下來（私密視窗、容量滿）就只是開一個照舊設定的前台。
  }
}

function optionalString(value: unknown): value is string | undefined {
  return value === undefined || typeof value === 'string'
}

/**
 * 取走給這個帳號、還沒過期的指令。不論內容對不對都先刪掉：
 * 留著的話下次開前台（或換人登入）會再被套用一次。
 */
export function takeAdminHandoff(
  accountId: string,
  nowMs: number,
  maxAgeMs = ADMIN_HANDOFF_MAX_AGE_MS,
): AdminHandoff | null {
  const store = storage()
  if (!store) return null
  let raw: string | null = null
  try {
    raw = store.getItem(ADMIN_HANDOFF_KEY)
  } catch {
    raw = null
  } finally {
    try {
      store.removeItem(ADMIN_HANDOFF_KEY)
    } catch {
      // 刪不掉也不能因此套用；下面照常檢查。
    }
  }
  if (!raw || !accountId) return null
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return null
  }
  if (!parsed || typeof parsed !== 'object') return null
  const item = parsed as Record<string, unknown>
  if (item.v !== 1 || item.accountId !== accountId) return null
  if (typeof item.createdAt !== 'number' || !Number.isFinite(item.createdAt)) return null
  const age = nowMs - item.createdAt
  // 未來的時間戳也不收：時鐘被調過或內容被改過，都不該當成剛按的。
  if (age < 0 || age > maxAgeMs) return null
  if (
    !optionalString(item.projectId)
    || !optionalString(item.characterId)
    || !optionalString(item.backgroundId)
    || !optionalString(item.backgroundUrl)
  ) return null
  return {
    v: 1,
    accountId,
    createdAt: item.createdAt,
    ...(item.projectId ? { projectId: item.projectId } : {}),
    ...(item.characterId ? { characterId: item.characterId } : {}),
    ...(item.backgroundId ? { backgroundId: item.backgroundId } : {}),
    ...(item.backgroundUrl ? { backgroundUrl: item.backgroundUrl } : {}),
  }
}
