/** 回答語言：指定後回覆與知識檢索都鎖在這個語言（後端 ChatRequest.language）。 */
export interface LockedLanguageOption {
  value: string
  label: string
}

export const LOCKED_LANGUAGES: readonly LockedLanguageOption[] = [
  { value: 'zh', label: '中文' },
  { value: 'en', label: 'English' },
  { value: 'es', label: 'Español' },
  { value: 'ja', label: '日本語' },
  { value: 'ko', label: '한국어' },
]

/** 空字串代表不鎖定；不認得的值一律當作不鎖定，不讓請求被後端 422 退回。 */
export function normalizeLockedLanguage(value: string | null | undefined): string {
  return LOCKED_LANGUAGES.some((option) => option.value === value) ? (value as string) : ''
}

/** 網址參數 ?lang=xx；其他值忽略。 */
export function languageFromSearch(search: string): string {
  return normalizeLockedLanguage(new URLSearchParams(search).get('lang'))
}

/** 優先順序：網址參數 ＞ 設定裡選的語言 ＞ 不鎖定。 */
export function resolveLockedLanguage(search: string, saved: string): string {
  return languageFromSearch(search) || normalizeLockedLanguage(saved)
}

export function urlLockedLanguage(): string {
  return typeof window === 'undefined' ? '' : languageFromSearch(window.location.search)
}

export function activeLockedLanguage(saved: string): string {
  return typeof window === 'undefined' ? normalizeLockedLanguage(saved) : resolveLockedLanguage(window.location.search, saved)
}
