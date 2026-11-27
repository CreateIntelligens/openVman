import type { BrowserFamily } from './useClientDiagnostics'

export type LoadFailureType = 'script' | 'wasm' | 'character_data' | 'unknown'

export class AvatarLoadError extends Error {
  constructor(readonly failureType: LoadFailureType, message: string, readonly cause: unknown) {
    super(message)
  }
}

export function classifyLoadFailure(error: unknown): LoadFailureType {
  return error instanceof AvatarLoadError ? error.failureType : 'unknown'
}

const LOAD_FAILURES_KEY = 'openvman.avatar.load_failures'

export function recordLoadFailure(): number {
  try {
    const storage = window.sessionStorage
    const stored = Number(storage.getItem(LOAD_FAILURES_KEY))
    const failures = Number.isSafeInteger(stored) && stored > 0 ? stored + 1 : 1
    storage.setItem(LOAD_FAILURES_KEY, String(failures))
    return failures
  } catch {
    return 0
  }
}

export function clearLoadFailures(): void {
  try {
    window.sessionStorage.removeItem(LOAD_FAILURES_KEY)
  } catch {
    // 私密瀏覽或儲存空間受限時仍可使用舞台。
  }
}

export function loadFailureAdvice(browser: BrowserFamily, failures: number): string {
  if (failures < 3) return ''
  const advice = []
  if (browser === 'line' || browser === 'facebook' || browser === 'instagram') {
    advice.push('請點右上角選單，改用預設瀏覽器（Safari 或 Chrome）開啟。')
  } else if (browser === 'ios_safari') {
    advice.push('若 iPhone 開著低耗電模式，請先關閉再重新整理。')
  }
  advice.push('也請確認網路連線正常。')
  return advice.join('\n')
}
