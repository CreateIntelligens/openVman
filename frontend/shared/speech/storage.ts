/**
 * 帳號作用域 localStorage 與舊鍵名自動遷移 (storage.ts, D11)
 *
 * 核心功能：
 * 1. 支援帳號隔離：scopeId 有值時為 key::accountId，避免共用瀏覽器時跨帳號污染偏好；
 * 2. 統一語音相關鍵名前綴為 speech.*（如 speech.tts_provider、speech.tts_voice）；
 * 3. 具備向後相容遷移機制（D11）：若新鍵不存在，自動搜尋舊鍵（如 avatar.tts_engine、brain-tts-provider），
 *    讀出後自動寫入新鍵，但「保留舊鍵不刪除」，留一版供舊版前端相容或安全降級；
 * 4. 存取全覆蓋 try/catch，防止無痕模式或 QuotaExceededError 導致應用崩潰。
 */

export const SPEECH_STORAGE_KEYS = {
  TTS_PROVIDER: 'speech.tts_provider',
  TTS_VOICE: 'speech.tts_voice',
  ASR_PROVIDER: 'speech.asr_provider',
} as const

export const LEGACY_KEY_MAP: Record<string, string[]> = {
  'speech.tts_provider': ['avatar.tts_engine', 'brain-tts-provider'],
  'speech.tts_voice': ['avatar.tts_voice', 'brain-tts-voice'],
  'speech.asr_provider': ['avatar.asr_provider', 'brain-asr-provider'],
}

let activeScope = ''

export function setStorageScope(accountId: string): void {
  activeScope = accountId ? accountId.trim() : ''
}

export function currentStorageScope(): string {
  return activeScope
}

export function scopedKey(key: string, scope = activeScope): string {
  return scope ? `${key}::${scope}` : key
}

function getStorage(): Storage | null {
  if (typeof window === 'undefined') return null
  try {
    return window.localStorage
  } catch {
    return null
  }
}

function getSafeItem(key: string): string | null {
  try {
    const storage = getStorage()
    return storage ? storage.getItem(key) : null
  } catch {
    return null
  }
}

function setSafeItem(key: string, value: string): void {
  try {
    const storage = getStorage()
    if (storage) {
      storage.setItem(key, value)
    }
  } catch {
    // 忽略配額超額或被禁用的錯誤
  }
}

function removeSafeItem(key: string): void {
  try {
    const storage = getStorage()
    if (storage) {
      storage.removeItem(key)
    }
  } catch {
    // 忽略錯誤
  }
}

/**
 * 讀取帳號作用域值。
 * 遷移順序（D11）：
 * 1. 新鍵 scoped (key::scope)
 * 2. 舊鍵 scoped (legacy::scope)：帳號自己的舊選擇，比沒綁帳號時留下的值可靠
 * 3. 新鍵 unscoped (key)
 * 4. 舊鍵 unscoped (legacy)
 * 從舊鍵讀出時遷入新鍵（有 scope 寫 scoped，沒有就寫 unscoped），舊鍵「保留不刪」。
 * 第 2 步必須排在第 3 步前面：還沒登入時遷出的 unscoped 新鍵，會擋住每個帳號自己
 * 的舊選擇。
 * 5. 若皆無，回傳 fallback ?? null。
 */
export function readScoped(key: string, fallback: string | null = null): string | null {
  const legacyKeys = LEGACY_KEY_MAP[key] ?? []

  const scopedNewVal = getSafeItem(scopedKey(key))
  if (scopedNewVal !== null) {
    return scopedNewVal
  }

  if (activeScope) {
    for (const legKey of legacyKeys) {
      const scopedLegVal = getSafeItem(scopedKey(legKey))
      if (scopedLegVal !== null) {
        setSafeItem(scopedKey(key), scopedLegVal)
        return scopedLegVal
      }
    }
  }

  const unscopedNewVal = getSafeItem(key)
  if (unscopedNewVal !== null) {
    return unscopedNewVal
  }

  for (const legKey of legacyKeys) {
    const unscopedLegVal = getSafeItem(legKey)
    if (unscopedLegVal !== null) {
      setSafeItem(scopedKey(key), unscopedLegVal)
      return unscopedLegVal
    }
  }

  return fallback
}

/**
 * 寫入作用域偏好值。
 */
export function writeScoped(key: string, value: string): void {
  setSafeItem(scopedKey(key), value)
}

/**
 * 移除偏好值。移除新鍵的 scoped 與 unscoped 項目。
 */
export function removeScoped(key: string): void {
  removeSafeItem(scopedKey(key))
  removeSafeItem(key)
}

/**
 * 檢查該偏好是否曾被存過。
 */
export function hasScoped(key: string): boolean {
  if (getSafeItem(scopedKey(key)) !== null || getSafeItem(key) !== null) {
    return true
  }

  const legacyKeys = LEGACY_KEY_MAP[key]
  if (legacyKeys) {
    for (const legKey of legacyKeys) {
      if (getSafeItem(scopedKey(legKey)) !== null || getSafeItem(legKey) !== null) {
        return true
      }
    }
  }

  return false
}
